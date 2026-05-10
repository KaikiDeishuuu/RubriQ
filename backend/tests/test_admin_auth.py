from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import require_admin_token
from app.core.config import settings
from app.main import app


def test_high_risk_endpoint_requires_admin_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "secret-token")
    monkeypatch.setattr(settings, "admin_api_token_required", False)

    client = TestClient(app)

    response = client.get("/api/storage/rendered/submissions/1/page.png")
    assert response.status_code == 401

    response = client.get(
        "/api/storage/rendered/submissions/1/page.png",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 403

    require_admin_token("Bearer secret-token")


def test_admin_token_required_without_token_is_service_error(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", None)
    monkeypatch.setattr(settings, "admin_api_token_required", True)

    client = TestClient(app)

    response = client.get("/api/storage/rendered/submissions/1/page.png")

    assert response.status_code == 503

    with pytest.raises(HTTPException) as exc_info:
        require_admin_token("Bearer anything")
    assert exc_info.value.status_code == 503


def test_auth_check_returns_ok_with_valid_bearer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "secret-token")
    monkeypatch.setattr(settings, "admin_api_token_required", False)

    client = TestClient(app)

    unauthenticated = client.get("/api/auth/check")
    assert unauthenticated.status_code == 401

    authenticated = client.get("/api/auth/check", headers={"Authorization": "Bearer secret-token"})
    assert authenticated.status_code == 200
    payload = authenticated.json()
    assert payload["ok"] is True
    assert payload["auth_required"] is True


def test_auth_status_is_public(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", None)
    monkeypatch.setattr(settings, "admin_api_token_required", False)

    client = TestClient(app)

    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"auth_required": False}


def test_create_exam_requires_admin_token_when_enforced(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "secret-token")
    monkeypatch.setattr(settings, "admin_api_token_required", False)

    client = TestClient(app)

    response = client.post("/api/exams", json={"title": "Midterm"})

    assert response.status_code == 401


def test_readonly_endpoints_require_admin_token_when_enforced(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "secret-token")
    monkeypatch.setattr(settings, "admin_api_token_required", False)

    client = TestClient(app)
    paths = [
        "/api/exams",
        "/api/exams/1",
        "/api/exams/1/questions",
        "/api/exams/1/results",
        "/api/exams/1/batches",
        "/api/exams/1/batches/2",
        "/api/exams/1/roster",
        "/api/submissions/1",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 401, f"{path} did not require auth"
