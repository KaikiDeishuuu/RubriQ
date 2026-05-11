from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.common import load_submission_detail, serialize_submission_detail
from app.api.deps import get_db, require_admin_token
from app.models import Submission, SubmissionStatus
from app.schemas.submission import DeductionSummaryUpdate, ProcessResponse, SubmissionDetail, TeacherFinalizedUpdate
from app.services.batch_pipeline import finalize_stale_active_submissions
from app.services.export import ExportBusyError, build_submission_review_pdf, export_slot
from app.services.pipeline import PipelineError, set_teacher_deduction_summary
from app.storage.local import get_storage_service
from app.utils.errors import public_error_message
from app.workers.tasks import process_submission_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["submissions"])

ACTIVE_SUBMISSION_STATUSES = {
    SubmissionStatus.processing.value,
    SubmissionStatus.rendering.value,
    SubmissionStatus.extracting.value,
    SubmissionStatus.grading.value,
}
STARTABLE_SUBMISSION_STATUSES = {
    SubmissionStatus.uploaded.value,
    SubmissionStatus.failed.value,
}


@router.get("/{submission_id}", response_model=SubmissionDetail)
def get_submission_detail(
    submission_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    submission = _load_submission_or_404(session, submission_id)
    return serialize_submission_detail(submission)


@router.get("/{submission_id}/export.pdf")
def export_submission_review_pdf(
    submission_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        with export_slot():
            pdf_bytes = build_submission_review_pdf(session, submission_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Submission request failed")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Submission request failed")) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="submission-{submission_id}-review.pdf"'},
    )


@router.post("/{submission_id}/process", response_model=ProcessResponse)
def start_submission_processing(
    submission_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    finalize_stale_active_submissions(session, submission_id=submission_id)
    submission = _load_submission_or_404(session, submission_id)
    if submission.batch_id is not None and not submission.split_confirmed:
        raise HTTPException(status_code=409, detail="Batch submission split must be confirmed before grading")
    exam = submission.exam
    if submission.batch_id is not None and exam is not None and exam.roster_status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="考试名单尚未确认，请先在「考试名单」步骤上传并确认名单后再开始批改。",
        )
    if submission.status in ACTIVE_SUBMISSION_STATUSES:
        return ProcessResponse(submission_id=submission.id, status=submission.status)
    if submission.status not in STARTABLE_SUBMISSION_STATUSES:
        raise HTTPException(status_code=409, detail="Submission has already been processed")
    claimed = session.execute(
        update(Submission)
        .where(Submission.id == submission.id, Submission.status.in_(STARTABLE_SUBMISSION_STATUSES))
        .values(status=SubmissionStatus.processing.value, error_message=None)
    ).rowcount
    session.commit()
    if not claimed:
        session.refresh(submission)
        return ProcessResponse(submission_id=submission.id, status=submission.status)
    process_submission_task.delay(submission.id)
    session.refresh(submission)
    return ProcessResponse(submission_id=submission.id, status=submission.status)


@router.put("/{submission_id}/deduction-summary", response_model=SubmissionDetail)
def update_deduction_summary(
    submission_id: int,
    payload: DeductionSummaryUpdate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_submission_or_404(session, submission_id)
    try:
        set_teacher_deduction_summary(session, submission_id, payload.summary, reset=payload.reset)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Submission request failed")) from exc
    return serialize_submission_detail(load_submission_detail(session, submission_id))


@router.put("/{submission_id}/teacher-finalized", response_model=SubmissionDetail)
def update_teacher_finalized(
    submission_id: int,
    payload: TeacherFinalizedUpdate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    submission = _load_submission_or_404(session, submission_id)
    submission.teacher_finalized = payload.teacher_finalized
    session.commit()
    return serialize_submission_detail(load_submission_detail(session, submission_id))


def _load_submission_or_404(session: Session, submission_id: int) -> Submission:
    try:
        return load_submission_detail(session, submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Submission request failed")) from exc


@router.delete("/{submission_id}")
def delete_submission(
    submission_id: int,
    session: Session = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    submission = _load_submission_or_404(session, submission_id)
    original_pdf_path = submission.original_pdf_path
    rendered_tree_path = f"rendered/submissions/{submission.id}"
    session.delete(submission)
    session.commit()
    storage = get_storage_service()
    try:
        storage.delete(original_pdf_path)
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete submission PDF %s: %s", original_pdf_path, exc)
    try:
        storage.delete_tree(rendered_tree_path)
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete rendered submission assets %s: %s", submission_id, exc)
    return {"message": f"Submission {submission_id} deleted"}
