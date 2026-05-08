from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.services.ai_client import ChatCompletionResult
from app.services.llm import StructuredJsonError, _parse_completion_content, call_structured_json
from app.schemas.ai import RubricParseResult


class SimpleResponse(BaseModel):
    value: str


class FakeClient:
    def __init__(self, name: str, calls: list[str], responses: list[str | Exception] | None = None) -> None:
        self.name = name
        self.calls = calls
        self.responses = responses or ['{"value": "ok"}']

    def chat_completion(self, **kwargs: Any) -> ChatCompletionResult:
        self.calls.append(f"{self.name}:{kwargs.get('model')}")
        response = self.responses.pop(0) if self.responses else '{"value": "ok"}'
        if isinstance(response, Exception):
            raise response
        return ChatCompletionResult(content=response, raw_response={})


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
    assert calls == ["grading:model"]


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
    assert calls == ["vision:model"]


def test_call_structured_json_uses_route_key_candidate_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda route_key: [
            SimpleNamespace(profile="grading", model=f"{route_key}-primary", base_url="https://one.test", api_key="one"),
        ],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda *_args: FakeClient("candidate", calls))
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    result = call_structured_json(
        model="legacy-model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        request_profile="grading",
        route_key="grading",
    )

    assert result.data.value == "ok"
    assert result.model == "grading-primary"
    assert result.route_key == "grading"
    assert result.candidate_index == 1
    assert result.fallback_used is False
    assert calls == ["candidate:grading-primary"]



def test_call_structured_json_uses_grading_review_route_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda route_key: [
            SimpleNamespace(profile="grading", model=f"{route_key}-model", base_url="https://one.test", api_key="one"),
        ],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda *_args: FakeClient("candidate", calls))
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    result = call_structured_json(
        model="legacy-model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        request_profile="grading",
        route_key="grading_review",
    )

    assert result.model == "grading_review-model"
    assert result.route_key == "grading_review"
    assert calls == ["candidate:grading_review-model"]


def test_call_structured_json_falls_back_to_second_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    clients = {
        "https://one.test": FakeClient("one", calls, [RuntimeError("first failed")]),
        "https://two.test": FakeClient("two", calls, ['{"value": "fallback ok"}']),
    }
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda _route_key: [
            SimpleNamespace(profile="grading", model="first-model", base_url="https://one.test", api_key="one"),
            SimpleNamespace(profile="grading", model="second-model", base_url="https://two.test", api_key="two"),
        ],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda base_url, _api_key: clients[base_url])
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    result = call_structured_json(
        model="legacy-model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        request_profile="grading",
        route_key="grading",
    )

    assert result.data.value == "fallback ok"
    assert result.model == "second-model"
    assert result.candidate_index == 2
    assert result.fallback_used is True
    assert calls == ["one:first-model", "two:second-model"]



def test_call_structured_json_stops_after_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    clients = {
        "https://one.test": FakeClient("one", calls, ['{"value": "first ok"}']),
        "https://two.test": FakeClient("two", calls, ['{"value": "should not call"}']),
    }
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda _route_key: [
            SimpleNamespace(profile="vision", model="first-model", base_url="https://one.test", api_key="one"),
            SimpleNamespace(profile="vision", model="second-model", base_url="https://two.test", api_key="two"),
        ],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda base_url, _api_key: clients[base_url])
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr("app.services.llm.build_multimodal_messages", lambda *_args, **_kwargs: [])

    result = call_structured_json(
        model="legacy-model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        image_paths=[],
        request_profile="vision",
        route_key="vision_student_extraction",
    )

    assert result.data.value == "first ok"
    assert calls == ["one:first-model"]



def test_call_structured_json_reports_all_candidate_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    clients = {
        "https://one.test": FakeClient("one", calls, [RuntimeError("first failed")]),
        "https://two.test": FakeClient("two", calls, [RuntimeError("second failed")]),
    }
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda _route_key: [
            SimpleNamespace(profile="grading", model="first-model", base_url="https://one.test", api_key="one"),
            SimpleNamespace(profile="grading", model="second-model", base_url="https://two.test", api_key="two"),
        ],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda base_url, _api_key: clients[base_url])
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    with pytest.raises(StructuredJsonError, match="first-model") as exc_info:
        call_structured_json(
            model="legacy-model",
            system_prompt_name="system.md",
            user_prompt_name="user.md",
            response_model=SimpleResponse,
            request_profile="grading",
            route_key="grading",
        )

    assert "second-model" in str(exc_info.value)
    assert calls == ["one:first-model", "two:second-model"]



def test_call_structured_json_repairs_json_within_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    client = FakeClient("one", calls, ['{"value": 3}', '{"value": "repaired"}'])
    monkeypatch.setattr(
        "app.services.llm._settings_model_candidates",
        lambda _route_key: [SimpleNamespace(profile="grading", model="repair-model", base_url="https://one.test", api_key="one")],
    )
    monkeypatch.setattr("app.services.llm.get_ai_client_for", lambda *_args: client)
    monkeypatch.setattr("app.services.llm.render_prompt", lambda *_args, **_kwargs: "prompt")

    result = call_structured_json(
        model="legacy-model",
        system_prompt_name="system.md",
        user_prompt_name="user.md",
        response_model=SimpleResponse,
        request_profile="grading",
        route_key="grading",
    )

    assert result.data.value == "repaired"
    assert result.model == "repair-model"
    assert calls == ["one:repair-model", "one:repair-model"]



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

    assert calls == ["grading:model", "vision:model"]
