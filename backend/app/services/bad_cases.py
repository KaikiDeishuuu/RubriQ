from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OcrBadCase
from app.storage.local import get_storage_service

logger = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "triaged", "ready", "exported", "discarded"}


class BadCaseError(ValueError):
    pass


def enqueue(
    session: Session,
    *,
    route_key: str,
    image_storage_path: str,
    ocr_raw_text: str | None,
    ocr_error_message: str | None,
    trigger_reason: str,
    image_hash: str,
    exam_id: int | None = None,
    submission_id: int | None = None,
    batch_id: int | None = None,
    batch_page_id: int | None = None,
    trigger_source: str = "auto",
    reporter_note: str | None = None,
) -> int | None:
    try:
        now = datetime.now(timezone.utc)
        with session.begin_nested():
            existing = _find_existing(session, image_hash=image_hash, route_key=route_key)
            if existing is not None:
                _refresh_existing_case(
                    existing,
                    trigger_reason=trigger_reason,
                    last_seen_at=now,
                    ocr_raw_text=ocr_raw_text,
                    ocr_error_message=ocr_error_message,
                    trigger_source=trigger_source,
                    reporter_note=reporter_note,
                )
                session.flush()
                return existing.id
            case = OcrBadCase(
                route_key=route_key,
                exam_id=exam_id,
                submission_id=submission_id,
                batch_id=batch_id,
                batch_page_id=batch_page_id,
                image_storage_path=image_storage_path,
                image_hash=image_hash,
                ocr_model=settings.paddle_ocr_model,
                ocr_raw_text=ocr_raw_text or "",
                ocr_error_message=ocr_error_message,
                trigger_reason=trigger_reason,
                trigger_source=trigger_source,
                reporter_note=reporter_note,
                last_seen_at=now,
            )
            session.add(case)
            session.flush()
            return case.id
    except IntegrityError as exc:
        existing = _find_existing(session, image_hash=image_hash, route_key=route_key)
        if existing is not None:
            return existing.id
        logger.warning("Failed to enqueue OCR bad case route=%s image=%s: %s", route_key, image_storage_path, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - bad-case collection must not block OCR workflows
        logger.warning("Failed to enqueue OCR bad case route=%s image=%s: %s", route_key, image_storage_path, exc)
        return None


def list_bad_cases(
    session: Session,
    *,
    route_key: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[OcrBadCase], int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    stmt = select(OcrBadCase)
    count_stmt = select(func.count(OcrBadCase.id))
    conditions = []
    if route_key:
        conditions.append(OcrBadCase.route_key == route_key)
    if status:
        conditions.append(OcrBadCase.status == status)
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        conditions.append(
            or_(
                OcrBadCase.ocr_raw_text.ilike(pattern),
                OcrBadCase.reporter_note.ilike(pattern),
                OcrBadCase.ground_truth_text.ilike(pattern),
            )
        )
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = session.execute(count_stmt).scalar_one()
    items = session.execute(
        stmt.order_by(OcrBadCase.last_seen_at.desc(), OcrBadCase.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(items), int(total)


def get_bad_case(session: Session, case_id: int) -> OcrBadCase:
    case = session.get(OcrBadCase, case_id)
    if case is None:
        raise BadCaseError(f"Bad case {case_id} not found")
    return case


def update_bad_case(
    session: Session,
    case_id: int,
    *,
    ground_truth_text: str | None = None,
    status: str | None = None,
    redact_pii: bool | None = None,
    reporter_note: str | None = None,
) -> OcrBadCase:
    case = get_bad_case(session, case_id)
    if ground_truth_text is not None:
        stripped = ground_truth_text.strip()
        case.ground_truth_text = stripped or None
        if stripped and case.status == "pending":
            case.status = "triaged"
    if reporter_note is not None:
        case.reporter_note = reporter_note.strip() or None
    if redact_pii is not None:
        case.redact_pii = redact_pii
    if status is not None:
        if status not in VALID_STATUSES:
            raise BadCaseError(f"Unsupported bad case status: {status}")
        if status == "ready" and not (case.ground_truth_text or "").strip():
            raise BadCaseError("ground_truth_text is required to mark ready")
        case.status = status
    session.commit()
    session.refresh(case)
    return case


def delete_bad_case(session: Session, case_id: int) -> None:
    case = get_bad_case(session, case_id)
    session.delete(case)
    session.commit()


def export_badcases_zip(
    session: Session,
    *,
    route_key: str | None = None,
    since_id: int | None = None,
) -> tuple[bytes, dict[str, int]]:
    stmt = select(OcrBadCase).where(
        OcrBadCase.status == "ready",
        OcrBadCase.ground_truth_text.is_not(None),
    )
    if route_key:
        stmt = stmt.where(OcrBadCase.route_key == route_key)
    if since_id is not None:
        stmt = stmt.where(OcrBadCase.id > since_id)
    cases = list(session.execute(stmt.order_by(OcrBadCase.id.asc())).scalars().all())
    if len(cases) > settings.badcase_export_max_cases:
        raise BadCaseError("BADCASE_EXPORT_MAX_CASES exceeded")
    from app.services.bad_cases_redact import create_placeholder_image, redact_image
    from app.services.ocr import read_cached_ocr_result

    storage = get_storage_service()
    now = datetime.now(timezone.utc)
    redaction_failed_count = 0
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.md", _export_readme())
            jsonl_rows: list[str] = []
            for case in cases:
                source_path = storage.path_for(case.image_storage_path)
                image_name = f"{case.id:05d}{source_path.suffix or '.png'}"
                export_path = tmp_root / image_name
                redaction_method = "none"
                redaction_failed = False
                if case.redact_pii:
                    cached = read_cached_ocr_result(source_path)
                    result = redact_image(
                        source_path,
                        case.route_key,
                        cached.regions if cached is not None else [],
                        export_path,
                        exam=case.exam,
                        submission=case.submission,
                    )
                    redaction_method = result.method
                    redaction_failed = not result.success
                    if redaction_failed:
                        redaction_failed_count += 1
                        create_placeholder_image(source_path, export_path, case.id)
                else:
                    export_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_path, export_path)
                archive.write(export_path, f"images/{image_name}")
                jsonl_rows.append(json.dumps(_export_row(case, image_name, redaction_method, redaction_failed), ensure_ascii=False))
                case.status = "exported"
                case.exported_at = now
            archive.writestr("cases.jsonl", "\n".join(jsonl_rows) + ("\n" if jsonl_rows else ""))
    session.commit()
    return buffer.getvalue(), {
        "exported_count": len(cases),
        "redaction_failed_count": redaction_failed_count,
    }


def stats(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(OcrBadCase.route_key, OcrBadCase.status, func.count(OcrBadCase.id)).group_by(
            OcrBadCase.route_key,
            OcrBadCase.status,
        )
    ).all()
    return [(str(route_key), str(status), int(count)) for route_key, status, count in rows]


def _export_readme() -> str:
    return "OCR bad cases export. Images are redacted when redact_pii is true; metadata is in cases.jsonl.\n"


def _export_row(case: OcrBadCase, image_name: str, redaction_method: str, redaction_failed: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": case.id,
        "route_key": case.route_key,
        "image_path": f"images/{image_name}",
        "image_hash": case.image_hash,
        "ocr_model": case.ocr_model,
        "ocr_raw_text": case.ocr_raw_text,
        "ocr_error_message": case.ocr_error_message,
        "trigger_reason": case.trigger_reason,
        "trigger_source": case.trigger_source,
        "ground_truth_text": case.ground_truth_text,
        "redact_pii": case.redact_pii,
        "redaction_method": redaction_method,
        "redaction_failed": redaction_failed,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "last_seen_at": case.last_seen_at.isoformat() if case.last_seen_at else None,
    }


def _find_existing(session: Session, *, image_hash: str, route_key: str) -> OcrBadCase | None:
    return session.execute(
        select(OcrBadCase).where(
            OcrBadCase.image_hash == image_hash,
            OcrBadCase.route_key == route_key,
        )
    ).scalar_one_or_none()


def _refresh_existing_case(
    case: OcrBadCase,
    *,
    trigger_reason: str,
    last_seen_at: datetime,
    ocr_raw_text: str | None,
    ocr_error_message: str | None,
    trigger_source: str,
    reporter_note: str | None,
) -> None:
    case.trigger_reason = trigger_reason
    case.last_seen_at = last_seen_at
    case.ocr_raw_text = ocr_raw_text or ""
    case.ocr_error_message = ocr_error_message
    if trigger_source == "manual":
        case.trigger_source = "manual"
        case.reporter_note = _append_reporter_note(case.reporter_note, reporter_note)


def _append_reporter_note(existing: str | None, new_note: str | None) -> str | None:
    normalized = (new_note or "").strip()
    if not normalized:
        return existing
    if not existing:
        return normalized
    return f"{existing}\n{normalized}"
