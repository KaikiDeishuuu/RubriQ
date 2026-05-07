from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.common import load_submission_detail, serialize_submission_detail
from app.api.deps import get_db
from app.models import Submission, SubmissionStatus
from app.schemas.submission import ProcessResponse, SubmissionDetail
from app.storage.local import get_storage_service
from app.workers.tasks import process_submission_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/{submission_id}", response_model=SubmissionDetail)
def get_submission_detail(submission_id: int, session: Session = Depends(get_db)):
    submission = _load_submission_or_404(session, submission_id)
    return serialize_submission_detail(submission)


@router.post("/{submission_id}/process", response_model=ProcessResponse)
def start_submission_processing(submission_id: int, session: Session = Depends(get_db)):
    submission = _load_submission_or_404(session, submission_id)
    if submission.batch_id is not None and not submission.split_confirmed:
        raise HTTPException(status_code=409, detail="Batch submission split must be confirmed before grading")
    if submission.status == SubmissionStatus.processing.value:
        return ProcessResponse(submission_id=submission.id, status=submission.status)
    submission.status = SubmissionStatus.processing.value
    submission.error_message = None
    session.commit()
    process_submission_task.delay(submission.id)
    session.refresh(submission)
    return ProcessResponse(submission_id=submission.id, status=submission.status)


def _load_submission_or_404(session: Session, submission_id: int) -> Submission:
    try:
        return load_submission_detail(session, submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{submission_id}")
def delete_submission(submission_id: int, session: Session = Depends(get_db)):
    submission = _load_submission_or_404(session, submission_id)
    storage = get_storage_service()
    try:
        storage.delete(submission.original_pdf_path)
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete submission PDF %s: %s", submission.original_pdf_path, exc)
    try:
        storage.delete_tree(f"rendered/submissions/{submission.id}")
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete rendered submission assets %s: %s", submission.id, exc)
    session.delete(submission)
    session.commit()
    return {"message": f"Submission {submission_id} deleted"}
