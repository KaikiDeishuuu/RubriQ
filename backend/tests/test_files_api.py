from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.core.config import settings
from app.db.base import Base
from app.main import app
from app.models import Exam, SubmissionPage


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    def fake_get_db():
        yield session

    app.dependency_overrides[deps.get_db] = fake_get_db
    try:
        yield TestClient(app), session, get_storage_service()
    finally:
        app.dependency_overrides.clear()
        session.close()
        get_storage_service.cache_clear()


def test_storage_endpoint_allows_referenced_file(client) -> None:
    test_client, session, storage = client
    stored = storage.save_text("rendered/submissions/1/pages/page-001.png", "image")
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    session.add(SubmissionPage(submission_id=1, page_no=1, image_path=stored.relative_path))
    session.commit()

    response = test_client.get(f"/api/storage/{stored.relative_path}")

    assert response.status_code == 200
    assert response.content == b"image"


def test_storage_endpoint_rejects_unreferenced_file(client) -> None:
    test_client, _session, storage = client
    stored = storage.save_text("unreferenced/file.txt", "secret")

    response = test_client.get(f"/api/storage/{stored.relative_path}")

    assert response.status_code == 404


def test_storage_endpoint_rejects_escaping_path(client) -> None:
    test_client, _session, _storage = client

    response = test_client.get("/api/storage/%2E%2E/outside.txt")

    assert response.status_code == 400


def test_storage_endpoint_returns_404_when_referenced_file_missing(client) -> None:
    test_client, session, _storage = client
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    session.add(SubmissionPage(submission_id=1, page_no=1, image_path="missing/page.png"))
    session.commit()

    response = test_client.get("/api/storage/missing/page.png")

    assert response.status_code == 404
