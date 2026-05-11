from __future__ import annotations

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import BatchStatus, BatchUploadMode, Exam, Submission, SubmissionBatch, SubmissionStatus
from app.workers import tasks


@pytest.fixture()
def session_factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(tasks, "SessionLocal", SessionLocal)
    return SessionLocal


def test_process_submission_task_skips_duplicate_active_message(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.rendering.value,
    )
    session.add(submission)
    session.commit()
    submission_id = submission.id
    session.close()
    called = False

    def fake_process_submission(_session, _submission_id):
        nonlocal called
        called = True

    monkeypatch.setattr(tasks, "process_submission", fake_process_submission)

    result = tasks.process_submission_task(submission_id)

    assert result == {"submission_id": submission_id, "status": SubmissionStatus.rendering.value}
    assert called is False


def test_process_submission_task_retries_once_on_soft_timeout(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.processing.value,
    )
    session.add(submission)
    session.commit()
    submission_id = submission.id
    session.close()

    monkeypatch.setattr(tasks, "process_submission", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))

    with pytest.raises(Retry):
        tasks.process_submission_task.run(submission_id)

    check_session = session_factory()
    stored_submission = check_session.get(Submission, submission_id)
    assert stored_submission.status == SubmissionStatus.processing.value
    assert stored_submission.error_message is None
    check_session.close()


def test_process_submission_task_marks_failed_after_timeout_retry_is_exhausted(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        batch_id=batch.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.processing.value,
        split_confirmed=True,
    )
    session.add(submission)
    session.commit()
    submission_id = submission.id
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "process_submission", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))
    monkeypatch.setattr(tasks.process_submission_task.request, "retries", 1, raising=False)

    with pytest.raises(SoftTimeLimitExceeded):
        tasks.process_submission_task.run(submission_id)

    check_session = session_factory()
    stored_submission = check_session.get(Submission, submission_id)
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_submission.status == SubmissionStatus.failed.value
    assert stored_submission.error_message == "Submission processing timed out"
    assert stored_batch.status == BatchStatus.completed_with_errors.value
    check_session.close()


def test_review_batch_grading_task_retries_once_on_soft_timeout(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="queued",
    )
    session.add(batch)
    session.commit()
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "review_batch_grading", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))

    with pytest.raises(Retry):
        tasks.review_batch_grading_task.run(batch_id)

    check_session = session_factory()
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_batch.ai_review_status == "queued"
    assert stored_batch.ai_review_error_message is None
    assert stored_batch.status == BatchStatus.grading.value
    check_session.close()


def test_review_batch_grading_task_marks_failed_after_timeout_retry_is_exhausted(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="running",
    )
    session.add(batch)
    session.commit()
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "review_batch_grading", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))
    monkeypatch.setattr(tasks.review_batch_grading_task.request, "retries", 1, raising=False)

    with pytest.raises(SoftTimeLimitExceeded):
        tasks.review_batch_grading_task.run(batch_id)

    check_session = session_factory()
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_batch.ai_review_status == "failed"
    assert stored_batch.ai_review_error_message == "Batch grading review timed out"
    assert stored_batch.status == BatchStatus.completed_with_errors.value
    check_session.close()
