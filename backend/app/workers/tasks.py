from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import update as sa_update

from app.db.session import SessionLocal
from app.models import Submission, SubmissionStatus
from app.services.batch_pipeline import prepare_batch_split, refresh_batch_grading_status, review_batch_grading, start_batch_grading
from app.services.pipeline import process_submission
from app.utils.errors import sanitized_error_summary
from app.workers.celery_app import celery_app

SUBMISSION_TIMEOUT_MESSAGE = "Submission processing timed out"
BATCH_REVIEW_TIMEOUT_MESSAGE = "Batch grading review timed out"
TIMEOUT_RETRY_COUNTDOWN_SECONDS = 10


def _can_retry_task(task) -> bool:
    return task.request.retries < task.max_retries


def _mark_submission_processing_for_retry(session, submission_id: int) -> None:
    submission = session.get(Submission, submission_id)
    if submission is None:
        return
    submission.status = SubmissionStatus.processing.value
    session.commit()


def _mark_submission_failed(session, submission_id: int, message: str) -> None:
    submission = session.get(Submission, submission_id)
    if submission is None:
        return
    batch_id = submission.batch_id
    submission.status = SubmissionStatus.failed.value
    submission.error_message = message
    session.commit()
    if batch_id is not None:
        refresh_batch_grading_status(session, batch_id)


def _mark_batch_review_failed(session, batch_id: int, message: str) -> None:
    from app.models import BatchStatus, SubmissionBatch

    batch = session.get(SubmissionBatch, batch_id)
    if batch is None:
        return
    batch.ai_review_status = "failed"
    batch.ai_review_error_message = message
    batch.status = BatchStatus.completed_with_errors.value
    session.commit()


@celery_app.task(name="app.workers.tasks.process_submission_task", bind=True, max_retries=1)
def process_submission_task(self, submission_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        submission = session.get(Submission, submission_id)
        if submission is not None and submission.batch_id is not None and not submission.split_confirmed:
            batch_id = submission.batch_id
            submission.status = SubmissionStatus.needs_review.value
            submission.error_message = "Batch submission split must be confirmed before grading"
            session.commit()
            refresh_batch_grading_status(session, batch_id)
            return {"submission_id": submission.id, "status": submission.status}
        if submission is not None and submission.status != SubmissionStatus.processing.value:
            if submission.batch_id is not None:
                refresh_batch_grading_status(session, submission.batch_id)
            return {"submission_id": submission.id, "status": submission.status}
        claimed = session.execute(
            sa_update(Submission)
            .where(Submission.id == submission_id, Submission.status == SubmissionStatus.processing.value)
            .values(status=SubmissionStatus.rendering.value)
        ).rowcount
        session.commit()
        if not claimed:
            submission = session.get(Submission, submission_id)
            if submission is None:
                raise RuntimeError(f"Submission {submission_id} not found")
            if submission.batch_id is not None:
                refresh_batch_grading_status(session, submission.batch_id)
            return {"submission_id": submission.id, "status": submission.status}
        submission = process_submission(session, submission_id)
        if submission.batch_id is not None:
            refresh_batch_grading_status(session, submission.batch_id)
        return {"submission_id": submission.id, "status": submission.status}
    except SoftTimeLimitExceeded:
        session.rollback()
        if _can_retry_task(self):
            _mark_submission_processing_for_retry(session, submission_id)
            raise self.retry(countdown=TIMEOUT_RETRY_COUNTDOWN_SECONDS)
        _mark_submission_failed(session, submission_id, SUBMISSION_TIMEOUT_MESSAGE)
        raise
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        session.rollback()
        _mark_submission_failed(session, submission_id, sanitized_error_summary(exc, "Submission processing failed"))
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.prepare_batch_split_task", soft_time_limit=1800, time_limit=2400)
def prepare_batch_split_task(batch_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        batch = prepare_batch_split(session, batch_id)
        return {"batch_id": batch.id, "status": batch.status}
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.start_batch_grading_task")
def start_batch_grading_task(batch_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        batch, queued_count = start_batch_grading(session, batch_id)
        return {"batch_id": batch.id, "status": batch.status, "queued_submission_count": queued_count}
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.review_batch_grading_task", bind=True, max_retries=1, soft_time_limit=1800, time_limit=2400)
def review_batch_grading_task(self, batch_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        batch = review_batch_grading(session, batch_id)
        return {"batch_id": batch.id, "status": batch.status, "ai_review_status": batch.ai_review_status}
    except SoftTimeLimitExceeded:
        session.rollback()
        if _can_retry_task(self):
            raise self.retry(countdown=TIMEOUT_RETRY_COUNTDOWN_SECONDS)
        _mark_batch_review_failed(session, batch_id, BATCH_REVIEW_TIMEOUT_MESSAGE)
        raise
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        session.rollback()
        _mark_batch_review_failed(session, batch_id, sanitized_error_summary(exc, "Batch grading review failed"))
        raise
    finally:
        session.close()
