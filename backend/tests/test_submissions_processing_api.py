from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.db.base import Base
from app.main import app
from app.models import Answer, Exam, Question, Submission, SubmissionStatus


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


def test_start_submission_processing_allows_single_submission_without_confirmed_roster(client_session, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.uploaded.value)
    submission.exam.roster_status = "needs_review"
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == SubmissionStatus.processing.value
    assert queued_ids == [submission.id]


def test_start_submission_processing_requires_confirmed_roster_for_batch_submission(client_session, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.uploaded.value)
    submission.batch_id = 1
    submission.split_confirmed = True
    submission.exam.roster_status = "needs_review"
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 409
    assert "考试名单" in response.json()["detail"]
    assert queued_ids == []


def test_update_teacher_finalized_toggles_submission_flag(client_session) -> None:
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.graded.value)

    response = test_client.put(f"/api/submissions/{submission.id}/teacher-finalized", json={"teacher_finalized": True})

    assert response.status_code == 200
    assert response.json()["teacher_finalized"] is True
    session.refresh(submission)
    assert submission.teacher_finalized is True

    response = test_client.put(f"/api/submissions/{submission.id}/teacher-finalized", json={"teacher_finalized": False})

    assert response.status_code == 200
    assert response.json()["teacher_finalized"] is False
    session.refresh(submission)
    assert submission.teacher_finalized is False


def test_get_submission_detail_returns_teacher_finalized(client_session) -> None:
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.graded.value)
    submission.teacher_finalized = True
    session.commit()

    response = test_client.get(f"/api/submissions/{submission.id}")

    assert response.status_code == 200
    assert response.json()["teacher_finalized"] is True


def test_update_teacher_finalized_returns_404_for_missing_submission(client_session) -> None:
    test_client, _session = client_session

    response = test_client.put("/api/submissions/999/teacher-finalized", json={"teacher_finalized": True})

    assert response.status_code == 404


def test_exam_results_rows_include_teacher_finalized(client_session) -> None:
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.graded.value)
    submission.teacher_finalized = True
    question = Question(exam_id=submission.exam_id, question_no="1", title="Q1", max_score=5, order_index=0)
    session.add(question)
    session.flush()
    session.add(
        Answer(
            submission_id=submission.id,
            question_id=question.id,
            extracted_answer="answer",
            score=4,
            max_score=5,
            confidence="high",
        )
    )
    session.commit()

    response = test_client.get(f"/api/exams/{submission.exam_id}/results")

    assert response.status_code == 200
    assert response.json()["rows"][0]["teacher_finalized"] is True


def _create_submission(session, status: str) -> Submission:
    exam = Exam(title="Sample", roster_status="confirmed")
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
