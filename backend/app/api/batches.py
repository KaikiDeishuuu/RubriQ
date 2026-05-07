from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.common import load_exam_detail
from app.api.deps import get_db
from app.core.config import settings
from app.models import BatchStatus, BatchUploadMode, SubmissionBatch
from app.schemas.batch import (
    BatchCandidatesUpdateRequest,
    BatchConfirmResponse,
    BatchDetail,
    BatchStartGradingResponse,
    BatchUploadResponse,
)
from app.services.batch_pipeline import (
    BatchPipelineError,
    confirm_batch_split,
    list_exam_batches,
    load_batch_detail,
    start_batch_grading,
    update_batch_candidates,
)
from app.storage.local import get_storage_service
from app.utils.files import validate_pdf_upload
from app.workers.tasks import prepare_batch_split_task

router = APIRouter(prefix="/exams/{exam_id}/batches", tags=["batches"])


@router.post("/upload", response_model=BatchUploadResponse)
async def upload_batch(
    exam_id: int,
    mode: BatchUploadMode = Form(...),
    file: UploadFile = File(...),
    pages_per_submission: int | None = Form(default=None),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    await _validate_batch_upload(mode, file, pages_per_submission)
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded batch file is too large")
    storage = get_storage_service()
    filename = file.filename or _default_source_filename(mode)
    if mode == BatchUploadMode.zip:
        storage_path = storage.unique_file_path(f"exams/{exam_id}/batches", filename, suffix=".zip")
    else:
        storage_path = storage.unique_pdf_path(f"exams/{exam_id}/batches", filename)
    stored = storage.save_bytes(storage_path, data)
    batch = SubmissionBatch(
        exam_id=exam_id,
        mode=mode.value,
        status=BatchStatus.uploaded.value,
        source_filename=filename,
        source_storage_path=stored.relative_path,
        pages_per_submission=pages_per_submission if mode == BatchUploadMode.combined_fixed else None,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    prepare_batch_split_task.delay(batch.id)
    return BatchUploadResponse(batch=BatchDetail.model_validate(load_batch_detail(session, batch.id)))


@router.get("", response_model=list[BatchDetail])
def list_batches(exam_id: int, session: Session = Depends(get_db)):
    _load_exam_or_404(session, exam_id)
    return [BatchDetail.model_validate(batch) for batch in list_exam_batches(session, exam_id)]


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch(exam_id: int, batch_id: int, session: Session = Depends(get_db)):
    batch = _load_batch_or_404(session, exam_id, batch_id)
    return BatchDetail.model_validate(batch)


@router.put("/{batch_id}/candidates", response_model=BatchDetail)
def update_candidates(
    exam_id: int,
    batch_id: int,
    payload: BatchCandidatesUpdateRequest,
    session: Session = Depends(get_db),
):
    _load_batch_or_404(session, exam_id, batch_id)
    try:
        batch = update_batch_candidates(session, batch_id, payload.candidates)
    except BatchPipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchDetail.model_validate(batch)


@router.post("/{batch_id}/confirm-split", response_model=BatchConfirmResponse)
def confirm_split(exam_id: int, batch_id: int, session: Session = Depends(get_db)):
    _load_batch_or_404(session, exam_id, batch_id)
    try:
        result = confirm_batch_split(session, batch_id)
    except BatchPipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchConfirmResponse(
        batch=BatchDetail.model_validate(result.batch),
        created_submission_count=result.created_submission_count,
        failed_candidate_count=result.failed_candidate_count,
    )


@router.post("/{batch_id}/start-grading", response_model=BatchStartGradingResponse)
def start_grading(exam_id: int, batch_id: int, session: Session = Depends(get_db)):
    _load_batch_or_404(session, exam_id, batch_id)
    try:
        batch, queued_count = start_batch_grading(session, batch_id)
    except BatchPipelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BatchStartGradingResponse(
        batch_id=batch.id,
        queued_submission_count=queued_count,
        status=BatchStatus(batch.status),
    )


async def _validate_batch_upload(
    mode: BatchUploadMode,
    file: UploadFile,
    pages_per_submission: int | None,
) -> None:
    if mode == BatchUploadMode.combined_fixed and (pages_per_submission is None or pages_per_submission < 1):
        raise HTTPException(status_code=400, detail="pages_per_submission is required for fixed-page mode")
    if mode == BatchUploadMode.zip:
        filename = file.filename or ""
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="ZIP batch mode requires a .zip file")
        await file.seek(0)
        return
    try:
        await validate_pdf_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_exam_or_404(session: Session, exam_id: int):
    try:
        return load_exam_detail(session, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _load_batch_or_404(session: Session, exam_id: int, batch_id: int) -> SubmissionBatch:
    try:
        batch = load_batch_detail(session, batch_id)
    except BatchPipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if batch.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


def _default_source_filename(mode: BatchUploadMode) -> str:
    return "batch.zip" if mode == BatchUploadMode.zip else "combined.pdf"
