from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


@dataclass(slots=True)
class ChatCompletionResult:
    content: str
    raw_response: dict[str, Any]


class AIClientError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        base_url = (base_url or settings.ai_base_url).rstrip("/")
        api_key = api_key or settings.ai_api_key
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.ai_request_timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> ChatCompletionResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = self._post_with_retries(payload)
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            preview = response.text.strip().replace("\n", " ")[:300]
            raise AIClientError(
                "AI gateway returned a non-JSON response. "
                "Check that AI_BASE_URL points to the OpenAI-compatible /v1 endpoint. "
                f"Response preview: {preview or '<empty>'}"
            ) from exc
        content = _extract_message_content(response_json)
        return ChatCompletionResult(content=content, raw_response=response_json)

    def _post_with_retries(self, payload: dict[str, Any]) -> httpx.Response:
        attempts = max(0, settings.ai_max_retries) + 1
        for attempt in range(attempts):
            try:
                response = self._client.post("/chat/completions", json=payload)
                if response.status_code in {429} or 500 <= response.status_code < 600:
                    if attempt < attempts - 1:
                        self._sleep_before_retry(attempt)
                        continue
                response.raise_for_status()
                return response
            except (httpx.NetworkError, httpx.TimeoutException):
                if attempt >= attempts - 1:
                    raise
                self._sleep_before_retry(attempt)
        raise RuntimeError("AI request retry loop exited unexpectedly")

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(max(0.0, settings.ai_retry_backoff_seconds) * (2**attempt))


@lru_cache(maxsize=1)
def get_ai_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient()


@lru_cache(maxsize=1)
def get_vision_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=settings.effective_vision_base_url,
        api_key=settings.effective_vision_api_key,
    )


@lru_cache(maxsize=1)
def get_grading_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=settings.effective_grading_base_url,
        api_key=settings.effective_grading_api_key,
    )


def _extract_message_content(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def image_path_to_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_multimodal_messages(system_prompt: str, user_prompt: str, image_paths: list[Path]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_path_to_data_url(image_path)},
            }
        )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def build_text_messages(system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
