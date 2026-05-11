from __future__ import annotations

from pathlib import Path

from PIL import Image

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.core.config import settings
from app.db.base import Base
from app.main import app
from app.models import Exam, ExamFile, Submission, SubmissionPage
from app.services import bad_cases


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


def test_post_badcase_rejects_unreferenced_path(client) -> None:
    test_client, _session, storage = client
    stored = storage.save_text("rendered/unknown/page.png", "image")

    response = test_client.post(
        "/api/badcases",
        json={"image_storage_path": stored.relative_path, "route_key": "vision_split_header"},
    )

    assert response.status_code == 400
    assert "referenced" in response.text


def test_post_badcase_creates_manual_case_for_referenced_path(client) -> None:
    test_client, session, storage = client
    stored = storage.save_text("rendered/submissions/1/pages/page-001.png", "image")
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(exam_id=exam.id, original_pdf_path="submissions/1.pdf")
    session.add(submission)
    session.flush()
    session.add(SubmissionPage(submission_id=submission.id, page_no=1, image_path=stored.relative_path, page_hash="a" * 64))
    session.commit()

    response = test_client.post(
        "/api/badcases",
        json={
            "image_storage_path": stored.relative_path,
            "route_key": "vision_student_extraction",
            "exam_id": exam.id,
            "submission_id": submission.id,
            "reporter_note": "OCR 错字",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trigger_source"] == "manual"
    assert payload["trigger_reason"] == "manual_report"
    assert payload["reporter_note"] == "OCR 错字"


def test_post_badcase_accepts_rendered_exam_file_page(client) -> None:
    test_client, session, storage = client
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    exam_file = ExamFile(
        exam_id=exam.id,
        file_type="rubric_pdf",
        original_filename="rubric.pdf",
        storage_path="uploads/rubric.pdf",
        page_count=2,
    )
    session.add(exam_file)
    session.commit()
    relative_path = f"rendered/exams/{exam.id}/rubric/{exam_file.id}/page-002.png"
    stored = storage.save_text(relative_path, "image")

    response = test_client.post(
        "/api/badcases",
        json={
            "image_storage_path": stored.relative_path,
            "route_key": "vision_rubric",
            "exam_id": exam.id,
            "reporter_note": "rubric OCR 错字",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_storage_path"] == relative_path
    assert payload["route_key"] == "vision_rubric"


def test_redact_preview_endpoint_creates_preview(client) -> None:
    test_client, session, storage = client
    image_path = storage.path_for("rendered/submissions/1/pages/page-001.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 40), "white").save(image_path)
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(exam_id=exam.id, original_pdf_path="submissions/1.pdf")
    session.add(submission)
    session.flush()
    session.add(SubmissionPage(submission_id=submission.id, page_no=1, image_path="rendered/submissions/1/pages/page-001.png", page_hash="c" * 64))
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_student_extraction",
        image_storage_path="rendered/submissions/1/pages/page-001.png",
        ocr_raw_text="姓名 张三",
        ocr_error_message=None,
        trigger_reason="manual_report",
        trigger_source="manual",
        image_hash="c" * 64,
        exam_id=exam.id,
        submission_id=submission.id,
    )
    session.commit()

    response = test_client.post(f"/api/badcases/{case_id}/redact-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == case_id
    assert payload["preview_storage_path"] == f"badcase-previews/{case_id}.png"


    test_client, session, storage = client
    stored = storage.save_text("rendered/submissions/1/pages/page-001.png", "image")
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_student_extraction",
        image_storage_path=stored.relative_path,
        ocr_raw_text="",
        ocr_error_message=None,
        trigger_reason="manual_report",
        trigger_source="manual",
        image_hash="b" * 64,
    )
    session.commit()

    response = test_client.put(f"/api/badcases/{case_id}", json={"status": "ready"})

    assert response.status_code == 400
    assert "ground_truth_text" in response.text
