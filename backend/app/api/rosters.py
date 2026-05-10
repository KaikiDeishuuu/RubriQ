from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.common import load_exam_detail, serialize_exam_detail
from app.api.deps import get_db, require_admin_token
from app.core.config import settings
from app.models import ExamFile
from app.schemas.exam import (
    ExamDetail,
    RosterDetail,
    RosterEntryRead,
    RosterReplaceRequest,
)
from app.services.roster import (
    RosterError,
    clear_roster,
    confirm_roster,
    load_roster_entries,
    parse_roster_pdf,
    parse_roster_table,
    replace_roster_entries,
)
from app.storage.local import get_storage_service
from app.utils.errors import public_error_message
from app.utils.files import read_upload_limited, validate_pdf_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exams/{exam_id}/roster", tags=["rosters"])

_TABLE_SOURCES = {"csv", "xlsx", "xlsm"}


@router.get("", response_model=RosterDetail)
def get_roster(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    entries = load_roster_entries(session, exam_id)
    return RosterDetail(
        exam_id=exam.id,
        roster_status=exam.roster_status,
        roster_error_message=exam.roster_error_message,
        entries=[RosterEntryRead.model_validate(entry) for entry in entries],
    )


@router.post("/upload", response_model=ExamDetail)
async def upload_roster(
    exam_id: int,
    file: UploadFile = File(...),
    source_kind: str | None = Form(default=None),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    suffix = _resolve_source_kind(source_kind, file.filename)
    if suffix == "pdf":
        await _validate_pdf_upload_or_400(file)
        data = await read_upload_limited(
            file,
            settings.max_upload_bytes,
            too_large_detail="Uploaded roster PDF is too large",
        )
        storage = get_storage_service()
        stored = storage.save_bytes(
            storage.unique_pdf_path(f"exams/{exam.id}/roster", file.filename or "roster.pdf"),
            data,
        )
        exam_file = ExamFile(
            exam_id=exam.id,
            file_type="roster_pdf",
            original_filename=file.filename or "roster.pdf",
            storage_path=stored.relative_path,
        )
        session.add(exam_file)
        exam.roster_status = "needs_review"
        exam.roster_error_message = None
        session.commit()
        return serialize_exam_detail(load_exam_detail(session, exam.id))

    if suffix in _TABLE_SOURCES:
        data = await read_upload_limited(
            file,
            settings.max_upload_bytes,
            too_large_detail="Uploaded roster file is too large",
        )
        try:
            parsed_entries = parse_roster_table(data, suffix)
        except RosterError as exc:
            raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
        if not parsed_entries:
            raise HTTPException(
                status_code=400,
                detail="Roster table is empty or could not be parsed (need a 姓名/学号 column)",
            )
        storage = get_storage_service()
        stored = storage.save_bytes(
            storage.unique_file_path(
                f"exams/{exam.id}/roster",
                file.filename or f"roster.{suffix}",
                suffix=f".{suffix}",
            ),
            data,
        )
        exam_file = ExamFile(
            exam_id=exam.id,
            file_type=f"roster_{suffix}",
            original_filename=file.filename or f"roster.{suffix}",
            storage_path=stored.relative_path,
        )
        session.add(exam_file)
        try:
            replace_roster_entries(session, exam.id, parsed_entries, source=suffix)
        except RosterError as exc:
            raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
        session.commit()
        return serialize_exam_detail(load_exam_detail(session, exam.id))

    raise HTTPException(status_code=400, detail=f"Unsupported roster source: {suffix}")


@router.post("/parse", response_model=ExamDetail)
def parse_roster(
    exam_id: int,
    exam_file_id: int | None = Query(default=None),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        parse_roster_pdf(session, exam_id, exam_file_id=exam_file_id)
    except RosterError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
    return serialize_exam_detail(load_exam_detail(session, exam_id))


@router.put("", response_model=ExamDetail)
def put_roster(
    exam_id: int,
    payload: RosterReplaceRequest,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        replace_roster_entries(session, exam_id, payload.entries, source=payload.source or "manual")
        session.commit()
    except RosterError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
    return serialize_exam_detail(load_exam_detail(session, exam_id))


@router.post("/confirm", response_model=ExamDetail)
def confirm(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        confirm_roster(session, exam_id)
    except RosterError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
    return serialize_exam_detail(load_exam_detail(session, exam_id))


@router.delete("", response_model=ExamDetail)
def delete_roster(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        clear_roster(session, exam_id)
    except RosterError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc
    return serialize_exam_detail(load_exam_detail(session, exam_id))


def _load_exam_or_404(session: Session, exam_id: int):
    try:
        return load_exam_detail(session, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Roster request failed")) from exc


async def _validate_pdf_upload_or_400(file: UploadFile) -> None:
    try:
        await validate_pdf_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Roster request failed")) from exc


def _resolve_source_kind(source_kind: str | None, filename: str | None) -> str:
    if source_kind:
        return source_kind.lower().lstrip(".")
    if filename:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix:
            return suffix
    return "pdf"
