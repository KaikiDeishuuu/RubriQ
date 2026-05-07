from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.services.ai_client import ChatCompletionResult
from app.services.llm import StructuredJsonError, _parse_completion_content, call_structured_json
from app.schemas.ai import RubricParseResult


class SimpleResponse(BaseModel):
    value: str


class FakeClient:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def chat_completion(self, **_: Any) -> ChatCompletionResult:
        self.calls.append(self.name)
        return ChatCompletionResult(content='{"value": "ok"}', raw_response={})


def test_parse_completion_content_rejects_empty_response() -> None:
    with pytest.raises(StructuredJsonError, match="empty response"):
        _parse_completion_content("", RubricParseResult)


def test_call_structured_json_routes_explicit_grading_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.services.llm.get_grading_client", lambda: FakeClient("grading", calls))
    monkeypatch.setattr("app.services.llm.get_vision_client", lambda: FakeClient("vision", calls))
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    result = call_structured_json(
        model="model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        request_profile="grading",
    )

    assert result.data.value == "ok"
    assert calls == ["grading"]


def test_call_structured_json_routes_explicit_vision_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake")
    monkeypatch.setattr("app.services.llm.get_grading_client", lambda: FakeClient("grading", calls))
    monkeypatch.setattr("app.services.llm.get_vision_client", lambda: FakeClient("vision", calls))
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr("app.services.llm.build_multimodal_messages", lambda *_args, **_kwargs: [])

    result = call_structured_json(
        model="model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        image_paths=[image_path],
        request_profile="vision",
    )

    assert result.data.value == "ok"
    assert calls == ["vision"]


def test_call_structured_json_preserves_legacy_profile_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake")
    monkeypatch.setattr("app.services.llm.get_grading_client", lambda: FakeClient("grading", calls))
    monkeypatch.setattr("app.services.llm.get_vision_client", lambda: FakeClient("vision", calls))
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr("app.services.llm.build_multimodal_messages", lambda *_args, **_kwargs: [])

    call_structured_json(
        model="model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
    )
    call_structured_json(
        model="model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        image_paths=[image_path],
    )

    assert calls == ["grading", "vision"]
