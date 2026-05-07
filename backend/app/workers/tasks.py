from __future__ import annotations

from app.db.session import SessionLocal
from app.models import Submission, SubmissionStatus
from app.services.batch_pipeline import prepare_batch_split, start_batch_grading
from app.services.pipeline import process_submission
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.process_submission_task")
def process_submission_task(submission_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        submission = session.get(Submission, submission_id)
        if submission is not None and submission.batch_id is not None and not submission.split_confirmed:
            submission.status = SubmissionStatus.needs_review.value
            submission.error_message = "Batch submission split must be confirmed before grading"
            session.commit()
            return {"submission_id": submission.id, "status": submission.status}
        reprocessable = {SubmissionStatus.uploaded.value, SubmissionStatus.processing.value, SubmissionStatus.rendering.value, SubmissionStatus.extracting.value, SubmissionStatus.grading.value}
        if submission is not None and submission.status not in reprocessable:
            return {"submission_id": submission.id, "status": submission.status}
        submission = process_submission(session, submission_id)
        return {"submission_id": submission.id, "status": submission.status}
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        submission = session.get(Submission, submission_id)
        if submission is not None:
            submission.status = SubmissionStatus.failed.value
            submission.error_message = str(exc)
            session.commit()
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
