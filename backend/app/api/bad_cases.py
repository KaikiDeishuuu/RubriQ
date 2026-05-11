from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_token
from app.api.files import _storage_path_is_referenced
from app.models import ExamFile, OcrBadCase
from app.schemas.bad_case import (
    BadCaseCreate,
    BadCaseListResponse,
    BadCaseRead,
    BadCaseRedactionPreview,
    BadCaseStatsItem,
    BadCaseUpdate,
)
from app.schemas.base import APIMessage
from app.services import bad_cases
from app.services.bad_cases_redact import create_placeholder_image, redact_image
from app.services.export import ExportBusyError, export_slot
from app.services.ocr import read_cached_ocr_result
from app.services.pdf import hash_file
from app.storage.local import get_storage_service

router = APIRouter(prefix="/badcases", tags=["badcases"])
RENDERED_EXAM_PAGE_RE = re.compile(r"^rendered/exams/(?P<exam_id>\d+)/(?P<kind>rubric|roster)/(?P<file_id>\d+)/page-(?P<page_no>\d{3})\.png$")


@router.post("", response_model=BadCaseRead)
def create_bad_case(
    payload: BadCaseCreate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    storage = get_storage_service()
    try:
        image_path = storage.path_for(payload.image_storage_path)
        relative_path = storage.relative_path_for(image_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not _storage_path_is_referenced(session, relative_path) and not _rendered_exam_page_is_valid(session, relative_path):
        raise HTTPException(status_code=400, detail="image_storage_path must be referenced by an existing record")
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    cached = read_cached_ocr_result(image_path)
    case_id = bad_cases.enqueue(
        session,
        route_key=payload.route_key,
        image_storage_path=relative_path,
        ocr_raw_text=cached.text if cached is not None else "",
        ocr_error_message=None,
        trigger_reason="manual_report",
        image_hash=hash_file(image_path),
        exam_id=payload.exam_id,
        submission_id=payload.submission_id,
        batch_id=payload.batch_id,
        batch_page_id=payload.batch_page_id,
        trigger_source="manual",
        reporter_note=payload.reporter_note,
    )
    if case_id is None:
        raise HTTPException(status_code=500, detail="Failed to create bad case")
    session.commit()
    return bad_cases.get_bad_case(session, case_id)


@router.get("", response_model=BadCaseListResponse)
def list_bad_cases(
    route_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    items, total = bad_cases.list_bad_cases(
        session,
        route_key=route_key,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return BadCaseListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=list[BadCaseStatsItem])
def bad_case_stats(
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    return [BadCaseStatsItem(route_key=route_key, status=status, count=count) for route_key, status, count in bad_cases.stats(session)]


@router.post("/export.zip")
def export_bad_cases_zip(
    route_key: str | None = Query(default=None),
    since_id: int | None = Query(default=None),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        with export_slot():
            payload, meta = bad_cases.export_badcases_zip(session, route_key=route_key, since_id=since_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except bad_cases.BadCaseError as exc:
        status_code = 413 if "BADCASE_EXPORT_MAX_CASES" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="ocr-badcases.zip"',
            "X-Exported-Count": str(meta["exported_count"]),
            "X-Redaction-Failed-Count": str(meta["redaction_failed_count"]),
        },
    )


@router.get("/{case_id}", response_model=BadCaseRead)
def get_bad_case(
    case_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        return bad_cases.get_bad_case(session, case_id)
    except bad_cases.BadCaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{case_id}", response_model=BadCaseRead)
def update_bad_case(
    case_id: int,
    payload: BadCaseUpdate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        return bad_cases.update_bad_case(
            session,
            case_id,
            ground_truth_text=payload.ground_truth_text,
            status=payload.status,
            redact_pii=payload.redact_pii,
            reporter_note=payload.reporter_note,
        )
    except bad_cases.BadCaseError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{case_id}", response_model=APIMessage)
def delete_bad_case(
    case_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        bad_cases.delete_bad_case(session, case_id)
    except bad_cases.BadCaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return APIMessage(message="Bad case deleted")


@router.post("/{case_id}/redact-preview", response_model=BadCaseRedactionPreview)
def create_redaction_preview(
    case_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    case = _load_case_or_404(session, case_id)
    storage = get_storage_service()
    source_path = storage.path_for(case.image_storage_path)
    preview_relative_path = f"badcase-previews/{case.id}.png"
    preview_path = storage.path_for(preview_relative_path)
    cached = read_cached_ocr_result(source_path)
    result = redact_image(
        source_path,
        case.route_key,
        cached.regions if cached is not None else [],
        preview_path,
        exam=case.exam,
        submission=case.submission,
    )
    if not result.success:
        create_placeholder_image(source_path, preview_path, case.id)
    return BadCaseRedactionPreview(
        id=case.id,
        preview_storage_path=preview_relative_path,
        redaction_method=result.method,
        redaction_failed=not result.success,
    )


@router.get("/{case_id}/redact-preview.png")
def get_redaction_preview(
    case_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_case_or_404(session, case_id)
    storage = get_storage_service()
    preview_path = storage.path_for(f"badcase-previews/{case_id}.png")
    if not preview_path.exists() or not preview_path.is_file():
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(str(preview_path), filename=Path(preview_path).name)


def _rendered_exam_page_is_valid(session: Session, relative_path: str) -> bool:
    match = RENDERED_EXAM_PAGE_RE.fullmatch(relative_path)
    if match is None:
        return False
    exam_id = int(match.group("exam_id"))
    file_id = int(match.group("file_id"))
    page_no = int(match.group("page_no"))
    file_type = "rubric_pdf" if match.group("kind") == "rubric" else "roster_pdf"
    exam_file = session.get(ExamFile, file_id)
    return bool(
        exam_file
        and exam_file.exam_id == exam_id
        and exam_file.file_type == file_type
        and exam_file.page_count is not None
        and 1 <= page_no <= exam_file.page_count
    )


def _load_case_or_404(session: Session, case_id: int) -> OcrBadCase:
    try:
        return bad_cases.get_bad_case(session, case_id)
    except bad_cases.BadCaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
