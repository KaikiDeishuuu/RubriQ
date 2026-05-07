from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.services.ai_client import (
    build_multimodal_messages,
    build_text_messages,
    get_vision_client,
    get_grading_client,
)
from app.services.prompts import render_prompt
from app.utils.json import parse_json_maybe

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class StructuredCompletion:
    data: BaseModel
    raw_text: str
    raw_response: dict[str, Any]
    prompt_text: str


class StructuredJsonError(RuntimeError):
    pass


def call_structured_json(
    *,
    model: str,
    system_prompt_name: str,
    user_prompt_name: str,
    response_model: type[T],
    prompt_variables: dict[str, Any] | None = None,
    image_paths: list[Path] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> StructuredCompletion:
    variables = prompt_variables or {}
    system_prompt = render_prompt(system_prompt_name, **variables)
    user_prompt = render_prompt(user_prompt_name, **variables)
    if image_paths:
        client = get_vision_client()
        messages = build_multimodal_messages(system_prompt, user_prompt, image_paths)
    else:
        client = get_grading_client()
        messages = build_text_messages(system_prompt, user_prompt)
    completion = client.chat_completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        parsed = _parse_completion_content(completion.content, response_model)
        data = response_model.model_validate(parsed)
        return StructuredCompletion(data=data, raw_text=completion.content, raw_response=completion.raw_response, prompt_text=user_prompt)
    except StructuredJsonError:
        raise
    except (ValidationError, ValueError, json.JSONDecodeError):
        try:
            repair_completion = _retry_with_json_repair(
                client=client,
                model=model,
                original_request=user_prompt,
                raw_response=completion.content,
                response_model=response_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise StructuredJsonError(_format_json_failure(completion.content, exc)) from exc
        return repair_completion


def _retry_with_json_repair(
    *,
    client: Any,
    model: str,
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
    completion = client.chat_completion(
        model=model,
        messages=build_text_messages(system_prompt, user_prompt),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    parsed = _parse_completion_content(completion.content, response_model)
    data = response_model.model_validate(parsed)
    return StructuredCompletion(data=data, raw_text=completion.content, raw_response=completion.raw_response, prompt_text=user_prompt)


def _parse_completion_content(text: str, response_model: type[T]) -> Any:
    if not text.strip():
        raise StructuredJsonError(
            f"AI model returned an empty response while {response_model.__name__} JSON was expected. "
            "Check that AI_BASE_URL points to the OpenAI-compatible /v1 endpoint and that the selected model supports the requested input."
        )
    return parse_json_maybe(text)


def _format_json_failure(raw_text: str, exc: Exception) -> str:
    preview = raw_text.strip().replace("\n", " ")[:300]
    if not preview:
        return f"AI model returned an empty response while JSON was expected: {exc}"
    return f"AI model returned invalid JSON: {exc}. Response preview: {preview}"
