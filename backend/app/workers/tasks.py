from __future__ import annotations

from app.db.session import SessionLocal
from app.models import Submission, SubmissionStatus
from app.services.pipeline import PipelineError, process_submission
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.process_submission_task")
def process_submission_task(submission_id: int) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        submission = session.get(Submission, submission_id)
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
