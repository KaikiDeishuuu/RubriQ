from __future__ import annotations

from sqlalchemy import update as sa_update

from app.db.session import SessionLocal
from app.models import Submission, SubmissionStatus
from app.services.batch_pipeline import prepare_batch_split, refresh_batch_grading_status, review_batch_grading, start_batch_grading
from app.services.pipeline import process_submission
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.process_submission_task")
def process_submission_task(submission_id: int) -> dict[str, int | str]:
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
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        submission = session.get(Submission, submission_id)
        if submission is not None:
            batch_id = submission.batch_id
            submission.status = SubmissionStatus.failed.value
            submission.error_message = str(exc)
            session.commit()
            if batch_id is not None:
                refresh_batch_grading_status(session, batch_id)
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.prepare_batch_split_task")
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


@celery_app.task(name="app.workers.tasks.review_batch_grading_task")
def review_batch_grading_task(batch_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        batch = review_batch_grading(session, batch_id)
        return {"batch_id": batch.id, "status": batch.status, "ai_review_status": batch.ai_review_status}
    finally:
        session.close()
