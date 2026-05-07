from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.common import load_submission_detail, serialize_submission_detail
from app.api.deps import get_db
from app.models import Submission, SubmissionStatus
from app.schemas.submission import ProcessResponse, SubmissionDetail, SubmissionSummary
from app.workers.tasks import process_submission_task

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/{submission_id}", response_model=SubmissionDetail)
def get_submission_detail(submission_id: int, session: Session = Depends(get_db)):
    submission = _load_submission_or_404(session, submission_id)
    return serialize_submission_detail(submission)


@router.post("/{submission_id}/process", response_model=ProcessResponse)
def start_submission_processing(submission_id: int, session: Session = Depends(get_db)):
    submission = _load_submission_or_404(session, submission_id)
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
