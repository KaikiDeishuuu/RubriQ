from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.db.base import Base
from app.main import app
from app.models import Exam, Submission, SubmissionStatus


@pytest.fixture()
def client_session():
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
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


@pytest.mark.parametrize("status", [SubmissionStatus.uploaded.value, SubmissionStatus.failed.value])
def test_start_submission_processing_queues_startable_statuses(client_session, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    test_client, session = client_session
    submission = _create_submission(session, status)
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == SubmissionStatus.processing.value
    assert queued_ids == [submission.id]
    assert session.get(Submission, submission.id).error_message is None


@pytest.mark.parametrize(
    "status",
    [
        SubmissionStatus.processing.value,
        SubmissionStatus.rendering.value,
        SubmissionStatus.extracting.value,
        SubmissionStatus.grading.value,
    ],
)
def test_start_submission_processing_does_not_requeue_active_statuses(client_session, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    test_client, session = client_session
    submission = _create_submission(session, status)
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert queued_ids == []


@pytest.mark.parametrize("status", [SubmissionStatus.graded.value, SubmissionStatus.needs_review.value])
def test_start_submission_processing_rejects_completed_statuses(client_session, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    test_client, session = client_session
    submission = _create_submission(session, status)
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 409
    assert queued_ids == []
    assert session.get(Submission, submission.id).status == status


def _create_submission(session, status: str) -> Submission:
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        original_pdf_path="submissions/sample.pdf",
        status=status,
        error_message="previous error",
    )
    session.add(submission)
    session.commit()
    return submission
