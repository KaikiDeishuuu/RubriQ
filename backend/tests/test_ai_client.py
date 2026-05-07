import pytest
import httpx

from app.services import ai_client
from app.services.ai_client import AIClientError, OpenAICompatibleClient


def test_chat_completion_retries_transient_status(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr(ai_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(ai_client.settings, "ai_max_retries", 1)
    client = OpenAICompatibleClient()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://ai.test")

    result = client.chat_completion(model="test-model", messages=[])

    assert result.content == "ok"
    assert calls == 2
    client.close()


def test_chat_completion_does_not_retry_validation_status(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"})

    monkeypatch.setattr(ai_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(ai_client.settings, "ai_max_retries", 2)
    client = OpenAICompatibleClient()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://ai.test")

    try:
        client.chat_completion(model="test-model", messages=[])
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("Expected HTTPStatusError")

    assert calls == 1
    client.close()


def test_chat_completion_reports_non_json_gateway_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not found")

    client = OpenAICompatibleClient()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://ai.test")

    with pytest.raises(AIClientError, match="non-JSON response"):
        client.chat_completion(model="test-model", messages=[])

    client.close()
