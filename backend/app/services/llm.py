from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import AIRouteKey, AIModelCandidate, settings
from app.services.ai_client import (
    build_multimodal_messages,
    build_text_messages,
    get_ai_client_for,
    get_grading_client,
    get_vision_client,
)
from app.services.prompts import render_prompt
from app.utils.json import parse_json_maybe

T = TypeVar("T", bound=BaseModel)
RequestProfile = Literal["grading", "vision"]

logger = logging.getLogger(__name__)
_GRADING_SEMAPHORE = threading.BoundedSemaphore(settings.ai_grading_global_concurrency)


@dataclass(slots=True)
class StructuredCompletion:
    data: BaseModel
    raw_text: str
    raw_response: dict[str, Any]
    prompt_text: str
    model: str
    profile: RequestProfile
    route_key: AIRouteKey | None
    candidate_index: int
    fallback_used: bool


class StructuredJsonError(RuntimeError):
    pass


def _resolve_request_profile(*, image_paths: list[Path] | None, request_profile: RequestProfile | None) -> RequestProfile:
    if request_profile is not None:
        return request_profile
    return "vision" if image_paths else "grading"


def call_structured_json(
    *,
    model: str,
    system_prompt_name: str,
    user_prompt_name: str,
    response_model: type[T],
    prompt_variables: dict[str, Any] | None = None,
    image_paths: list[Path] | None = None,
    request_profile: RequestProfile | None = None,
    route_key: AIRouteKey | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> StructuredCompletion:
    variables = prompt_variables or {}
    system_prompt = render_prompt(system_prompt_name, **variables)
    user_prompt = render_prompt(user_prompt_name, **variables)
    candidates = _resolve_model_candidates(model=model, image_paths=image_paths, request_profile=request_profile, route_key=route_key)
    candidate_errors: list[str] = []
    for candidate_index, candidate in enumerate(candidates, start=1):
        try:
            return _call_structured_json_candidate(
                candidate=candidate,
                candidate_index=candidate_index,
                route_key=route_key,
                use_profile_client=route_key is None,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                image_paths=image_paths,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001 - later model candidates are the fallback boundary
            candidate_errors.append(_format_candidate_error(candidate_index, candidate, exc))
            if candidate_index < len(candidates):
                logger.warning(
                    "LLM candidate failed; trying fallback route_key=%s profile=%s model=%s candidate=%s/%s error=%s",
                    route_key or candidate.profile,
                    candidate.profile,
                    candidate.model,
                    candidate_index,
                    len(candidates),
                    exc,
                )
                continue
            raise StructuredJsonError(_format_chain_failure(candidate_errors)) from exc
    raise StructuredJsonError("No AI model candidates were configured")


def _resolve_model_candidates(
    *,
    model: str,
    image_paths: list[Path] | None,
    request_profile: RequestProfile | None,
    route_key: AIRouteKey | None,
) -> list[AIModelCandidate]:
    if route_key is not None:
        return _settings_model_candidates(route_key)
    profile = _resolve_request_profile(image_paths=image_paths, request_profile=request_profile)
    if profile == "vision":
        return [
            AIModelCandidate(
                profile="vision",
                model=model,
                base_url=settings.effective_vision_base_url,
                api_key=settings.effective_vision_api_key,
            )
        ]
    return [
        AIModelCandidate(
            profile="grading",
            model=model,
            base_url=settings.effective_grading_base_url,
            api_key=settings.effective_grading_api_key,
        )
    ]


def _settings_model_candidates(route_key: AIRouteKey) -> list[AIModelCandidate]:
    return settings.ai_model_candidates(route_key)



def _call_structured_json_candidate(
    *,
    candidate: AIModelCandidate,
    candidate_index: int,
    route_key: AIRouteKey | None,
    use_profile_client: bool,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    image_paths: list[Path] | None,
    max_tokens: int,
    temperature: float,
) -> StructuredCompletion:
    client = _client_for_candidate(candidate, use_profile_client=use_profile_client)
    messages = (
        build_multimodal_messages(system_prompt, user_prompt, image_paths or [])
        if candidate.profile == "vision"
        else build_text_messages(system_prompt, user_prompt)
    )
    completion = _chat_completion_with_grading_limit(
        client=client,
        request_profile=candidate.profile,
        model=candidate.model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        request_stage="initial",
    )
    try:
        parsed = _parse_completion_content(completion.content, response_model)
        data = response_model.model_validate(parsed)
        return _structured_completion(
            data=data,
            completion=completion,
            user_prompt=user_prompt,
            candidate=candidate,
            route_key=route_key,
            candidate_index=candidate_index,
        )
    except StructuredJsonError:
        time.sleep(2.0)
        retry_completion = _chat_completion_with_grading_limit(
            client=client,
            request_profile=candidate.profile,
            model=candidate.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            request_stage="structured_json_retry",
        )
        parsed = _parse_completion_content(retry_completion.content, response_model)
        data = response_model.model_validate(parsed)
        return _structured_completion(
            data=data,
            completion=retry_completion,
            user_prompt=user_prompt,
            candidate=candidate,
            route_key=route_key,
            candidate_index=candidate_index,
        )
    except (ValidationError, ValueError, json.JSONDecodeError):
        try:
            return _retry_with_json_repair(
                client=client,
                request_profile=candidate.profile,
                model=candidate.model,
                route_key=route_key,
                candidate_index=candidate_index,
                original_request=user_prompt,
                raw_response=completion.content,
                response_model=response_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (StructuredJsonError, ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise StructuredJsonError(_format_json_failure(completion.content, exc)) from exc


def _client_for_candidate(candidate: AIModelCandidate, *, use_profile_client: bool) -> Any:
    if not use_profile_client:
        return get_ai_client_for(candidate.base_url, candidate.api_key)
    return get_vision_client() if candidate.profile == "vision" else get_grading_client()


def _structured_completion(
    *,
    data: BaseModel,
    completion: Any,
    user_prompt: str,
    candidate: AIModelCandidate,
    route_key: AIRouteKey | None,
    candidate_index: int,
) -> StructuredCompletion:
    return StructuredCompletion(
        data=data,
        raw_text=completion.content,
        raw_response=completion.raw_response,
        prompt_text=user_prompt,
        model=candidate.model,
        profile=candidate.profile,
        route_key=route_key,
        candidate_index=candidate_index,
        fallback_used=candidate_index > 1,
    )


def _retry_with_json_repair(
    *,
    client: Any,
    request_profile: RequestProfile,
    model: str,
    route_key: AIRouteKey | None,
    candidate_index: int,
    original_request: str,
    raw_response: str,
    response_model: type[T],
    max_tokens: int,
    temperature: float,
) -> StructuredCompletion:
    system_prompt = render_prompt("json_repair.system.md")
    schema_example = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
    user_prompt = render_prompt(
        "json_repair.user.md",
        original_request=original_request,
        schema_example=schema_example,
        raw_response=raw_response,
    )
    completion = _chat_completion_with_grading_limit(
        client=client,
        request_profile=request_profile,
        model=model,
        messages=build_text_messages(system_prompt, user_prompt),
        temperature=temperature,
        max_tokens=max_tokens,
        request_stage="json_repair_retry",
    )
    parsed = _parse_completion_content(completion.content, response_model)
    data = response_model.model_validate(parsed)
    return StructuredCompletion(
        data=data,
        raw_text=completion.content,
        raw_response=completion.raw_response,
        prompt_text=user_prompt,
        model=model,
        profile=request_profile,
        route_key=route_key,
        candidate_index=candidate_index,
        fallback_used=candidate_index > 1,
    )


def _chat_completion_with_grading_limit(
    *,
    client: Any,
    request_profile: RequestProfile,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    request_stage: str,
) -> Any:
    started_at = time.perf_counter()
    try:
        if request_profile != "grading":
            return client.chat_completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        with _GRADING_SEMAPHORE:
            return client.chat_completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
    finally:
        duration = time.perf_counter() - started_at
        if request_profile == "grading":
            logger.info(
                "Grading LLM call completed stage=%s model=%s duration_seconds=%.2f",
                request_stage,
                model,
                duration,
            )


def _parse_completion_content(text: str, response_model: type[T]) -> Any:
    if not text.strip():
        raise StructuredJsonError(
            f"AI model returned an empty response while {response_model.__name__} JSON was expected. "
            "Check that AI_BASE_URL points to the OpenAI-compatible /v1 endpoint and that the selected model supports the requested input."
        )
    return parse_json_maybe(text)


def _format_candidate_error(candidate_index: int, candidate: AIModelCandidate, exc: Exception) -> str:
    return f"#{candidate_index} profile={candidate.profile} model={candidate.model}: {exc}"


def _format_chain_failure(candidate_errors: list[str]) -> str:
    return "All AI model candidates failed: " + " | ".join(candidate_errors)


def _format_json_failure(raw_text: str, exc: Exception) -> str:
    preview = raw_text.strip().replace("\n", " ")[:300]
    if not preview:
        return f"AI model returned an empty response while JSON was expected: {exc}"
    return f"AI model returned invalid JSON: {exc}. Response preview: {preview}"
