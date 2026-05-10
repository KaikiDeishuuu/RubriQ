from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import literal, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_token
from app.models import BatchPage, BatchSplitCandidate, ExamFile, Submission, SubmissionBatch, SubmissionPage
from app.storage.local import get_storage_service

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/{file_path:path}")
def read_storage_file(
    file_path: str,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    storage = get_storage_service()
    try:
        absolute_path = storage.path_for(file_path)
        relative_path = storage.relative_path_for(absolute_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not _storage_path_is_referenced(session, relative_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not absolute_path.exists() or not absolute_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(absolute_path), filename=Path(relative_path).name)


def _storage_path_is_referenced(session: Session, relative_path: str) -> bool:
    target = literal(relative_path)
    stmt = union_all(
        select(literal(1)).where(ExamFile.storage_path == target),
        select(literal(1)).where(Submission.original_pdf_path == target),
        select(literal(1)).where(SubmissionPage.image_path == target),
        select(literal(1)).where(SubmissionBatch.source_storage_path == target),
        select(literal(1)).where(BatchPage.image_path == target),
        select(literal(1)).where(BatchSplitCandidate.source_storage_path == target),
    ).limit(1)
    return session.execute(stmt).first() is not None
