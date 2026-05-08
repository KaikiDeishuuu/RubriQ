from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import BatchPage, BatchSplitCandidate, ExamFile, Submission, SubmissionBatch, SubmissionPage
from app.storage.local import get_storage_service

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/{file_path:path}")
def read_storage_file(file_path: str, session: Session = Depends(get_db)):
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
    columns = (
        ExamFile.storage_path,
        Submission.original_pdf_path,
        SubmissionPage.image_path,
        SubmissionBatch.source_storage_path,
        BatchPage.image_path,
        BatchSplitCandidate.source_storage_path,
    )
    for column in columns:
        if session.execute(select(column).where(column == relative_path).limit(1)).first() is not None:
            return True
    return False
