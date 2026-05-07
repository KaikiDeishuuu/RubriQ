from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.storage.local import get_storage_service

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/{file_path:path}")
def read_storage_file(file_path: str):
    storage = get_storage_service()
    try:
        absolute_path = storage.path_for(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not absolute_path.exists() or not absolute_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(absolute_path), filename=Path(file_path).name)
