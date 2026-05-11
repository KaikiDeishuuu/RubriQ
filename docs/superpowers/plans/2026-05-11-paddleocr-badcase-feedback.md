# PaddleOCR Bad Case Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an admin-only PaddleOCR bad-case collection, triage, redaction preview, and ZIP export workflow for automatic OCR failures and manual teacher reports.

**Architecture:** Add a dedicated `ocr_bad_cases` database table and service layer as the single write/update/export boundary. Extend the OCR cache schema to preserve region bboxes, then wire automatic collection into existing OCR failure points and manual reporting into review pages. The frontend adds a protected `/badcases` admin page plus reusable report buttons that call the new API.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Pillow, pytest, React 18, TypeScript, Vite.

---

## Existing Patterns To Follow

- Backend tests run from repo root with `.venv/bin/python -m pytest backend/tests -q`.
- Frontend typecheck runs with `npm --prefix frontend run typecheck`.
- API routers live in `backend/app/api/` and are registered in `backend/app/api/router.py`.
- Protected endpoints use `Depends(require_admin_token)` from `backend/app/api/deps.py`.
- SQLAlchemy entities live in `backend/app/models/entities.py` and are exported from `backend/app/models/__init__.py`.
- Migrations are sequential in `backend/alembic/versions/`; the next revision is `0009_add_ocr_bad_cases` with `down_revision = "0008_question_no_unique"`.
- File access is fail-closed through `/api/storage/{path}` and `backend/app/api/files.py::_storage_path_is_referenced`.
- Export endpoints must use `backend/app/services/export.py::export_slot`.
- Rubric and roster rendered page images are currently written under `rendered/exams/...` but are not individually stored in DB rows; manual reporting for those pages must either report the generated storage path after render or validate it via the owning `ExamFile` rendered-page convention.

## File Structure

### Backend files

- Create `backend/alembic/versions/0009_add_ocr_bad_cases.py` — create/drop `ocr_bad_cases` table, indexes, and uniqueness constraint.
- Modify `backend/app/models/entities.py` — add `OcrBadCase` entity and relationships from existing entities.
- Modify `backend/app/models/__init__.py` — export `OcrBadCase`.
- Modify `backend/app/core/config.py` — add `BADCASE_REDACT_SALT`, `BADCASE_EXPORT_MAX_CASES`, `BADCASE_TOP_STRIP_RATIO` validators.
- Create `backend/app/schemas/bad_case.py` — Pydantic request/response schemas.
- Create `backend/app/services/bad_cases.py` — enqueue, list/detail/update/delete/stats/export service functions.
- Create `backend/app/services/bad_cases_redact.py` — PII bbox detection, image redaction, placeholder generation.
- Modify `backend/app/services/ocr.py` — add `OCRRegion`, cache schema support, region extraction, route-aware empty/error enqueue.
- Modify `backend/app/services/batch_pipeline.py` — enqueue split-header reject/error cases after header OCR acceptance decision.
- Modify `backend/app/api/files.py` — consider bad-case image and redaction preview paths referenced.
- Create `backend/app/api/bad_cases.py` — admin API endpoints.
- Modify `backend/app/api/router.py` — register bad-case router.
- Modify `backend/app/services/pipeline.py` — pass route context to OCR reference builder where needed.
- Modify `backend/app/services/roster.py` — pass route context to OCR reference builder where needed.
- Add tests in `backend/tests/test_bad_cases.py`, `backend/tests/test_bad_cases_api.py`, `backend/tests/test_bad_cases_redact.py`, and extend `backend/tests/test_ocr.py`, `backend/tests/test_batch_pipeline.py`, `backend/tests/test_config.py`, `backend/tests/test_files_api.py`.

### Frontend files

- Modify `frontend/src/lib/types.ts` — add bad-case route/status/reason types and DTOs.
- Modify `frontend/src/lib/api.ts` — add bad-case API helpers and ZIP download helper.
- Create `frontend/src/lib/badcases.ts` — keying/filter helpers for report button state and query strings.
- Create `frontend/src/components/BadCaseReportButton.tsx` — reusable modal/button for manual OCR reporting.
- Create `frontend/src/components/BadCaseDrawer.tsx` — admin detail drawer with image, OCR text, GT, status actions.
- Create `frontend/src/pages/BadCasesPage.tsx` — admin list/filter/KPI/export page.
- Modify `frontend/src/App.tsx` — add `/badcases` route.
- Modify `frontend/src/components/AppShell.tsx` — add `Bad Cases` nav entry.
- Modify `frontend/src/pages/RubricReviewPage.tsx`, `RosterPage.tsx`, `SubmissionUploadPage.tsx`, `SubmissionReviewPage.tsx` — integrate report buttons where image paths are available.
- Add tests in `frontend/tests/badcases.test.ts`.

---

## Task 1: Backend data model, config, and schemas

**Files:**
- Create: `backend/alembic/versions/0009_add_ocr_bad_cases.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/schemas/bad_case.py`
- Test: `backend/tests/test_config.py`
- Test: `backend/tests/test_bad_cases.py`

- [ ] **Step 1: Write failing config tests**

Add these tests to `backend/tests/test_config.py`:

```python
def test_badcase_settings_exist_and_have_safe_defaults() -> None:
    assert settings.badcase_export_max_cases == 500
    assert 0 < settings.badcase_top_strip_ratio <= 1
    assert isinstance(settings.badcase_redact_salt, str | type(None))


def test_invalid_badcase_settings_are_rejected() -> None:
    with pytest.raises(ValidationError, match="BADCASE_EXPORT_MAX_CASES"):
        _settings(BADCASE_EXPORT_MAX_CASES=0)
    with pytest.raises(ValidationError, match="BADCASE_TOP_STRIP_RATIO"):
        _settings(BADCASE_TOP_STRIP_RATIO=0)
    with pytest.raises(ValidationError, match="BADCASE_TOP_STRIP_RATIO"):
        _settings(BADCASE_TOP_STRIP_RATIO=1.5)
```

- [ ] **Step 2: Run config tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_config.py::test_badcase_settings_exist_and_have_safe_defaults backend/tests/test_config.py::test_invalid_badcase_settings_are_rejected -q
```

Expected: FAIL because `Settings` has no bad-case fields.

- [ ] **Step 3: Implement config fields and validators**

In `backend/app/core/config.py`, add fields near export/OCR settings:

```python
badcase_redact_salt: str | None = Field(default=None, alias="BADCASE_REDACT_SALT")
badcase_export_max_cases: int = Field(default=500, alias="BADCASE_EXPORT_MAX_CASES")
badcase_top_strip_ratio: float = Field(default=0.12, alias="BADCASE_TOP_STRIP_RATIO")
```

Add validators:

```python
@field_validator("badcase_export_max_cases")
@classmethod
def _validate_badcase_export_max_cases(cls, value: int) -> int:
    if value < 1:
        raise ValueError("BADCASE_EXPORT_MAX_CASES must be at least 1")
    return value

@field_validator("badcase_top_strip_ratio")
@classmethod
def _validate_badcase_top_strip_ratio(cls, value: float) -> float:
    if value <= 0 or value > 1:
        raise ValueError("BADCASE_TOP_STRIP_RATIO must be greater than 0 and at most 1")
    return value
```

Update `_settings()` defaults in `backend/tests/test_config.py` with:

```python
"BADCASE_EXPORT_MAX_CASES": 500,
"BADCASE_TOP_STRIP_RATIO": 0.12,
"BADCASE_REDACT_SALT": None,
```

- [ ] **Step 4: Run config tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing model/schema tests**

Create `backend/tests/test_bad_cases.py` with at least this scaffold:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import Exam, OcrBadCase


@pytest.fixture()
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        get_storage_service.cache_clear()


def test_ocr_bad_case_model_persists_core_fields(session) -> None:
    exam = Exam(title="Midterm")
    session.add(exam)
    session.flush()
    case = OcrBadCase(
        route_key="vision_split_header",
        exam_id=exam.id,
        image_storage_path="rendered/batches/1/headers/page-001.png",
        image_hash="a" * 64,
        ocr_model="PaddleOCR-VL-1.5",
        ocr_raw_text="姓名 张三",
        trigger_reason="regex_no_student_id",
        trigger_source="auto",
    )
    session.add(case)
    session.commit()

    stored = session.execute(select(OcrBadCase)).scalar_one()

    assert stored.status == "pending"
    assert stored.redact_pii is True
    assert stored.exam_id == exam.id
    assert stored.image_storage_path.endswith("page-001.png")
```

- [ ] **Step 6: Run model test and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py::test_ocr_bad_case_model_persists_core_fields -q
```

Expected: FAIL because `OcrBadCase` does not exist.

- [ ] **Step 7: Implement migration and ORM model**

Create `backend/alembic/versions/0009_add_ocr_bad_cases.py`:

```python
"""add ocr bad cases

Revision ID: 0009_add_ocr_bad_cases
Revises: 0008_question_no_unique
Create Date: 2026-05-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_add_ocr_bad_cases"
down_revision = "0008_question_no_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_bad_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_key", sa.String(length=50), nullable=False),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("submission_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_page_id", sa.Integer(), sa.ForeignKey("batch_pages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("image_storage_path", sa.String(length=1024), nullable=False),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("ocr_model", sa.String(length=255), nullable=False),
        sa.Column("ocr_raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("ocr_error_message", sa.Text(), nullable=True),
        sa.Column("trigger_reason", sa.String(length=50), nullable=False),
        sa.Column("trigger_source", sa.String(length=20), nullable=False),
        sa.Column("reporter_note", sa.Text(), nullable=True),
        sa.Column("ground_truth_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("redact_pii", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("image_hash", "route_key", name="uq_ocr_bad_cases_image_route"),
    )
    op.create_index("ix_ocr_bad_cases_status", "ocr_bad_cases", ["status"])
    op.create_index("ix_ocr_bad_cases_route_key", "ocr_bad_cases", ["route_key"])


def downgrade() -> None:
    op.drop_index("ix_ocr_bad_cases_route_key", table_name="ocr_bad_cases")
    op.drop_index("ix_ocr_bad_cases_status", table_name="ocr_bad_cases")
    op.drop_table("ocr_bad_cases")
```

Add `OcrBadCase` to `backend/app/models/entities.py`:

```python
class OcrBadCase(Base, TimestampMixin):
    __tablename__ = "ocr_bad_cases"
    __table_args__ = (
        UniqueConstraint("image_hash", "route_key", name="uq_ocr_bad_cases_image_route"),
        Index("ix_ocr_bad_cases_status", "status"),
        Index("ix_ocr_bad_cases_route_key", "route_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_key: Mapped[str] = mapped_column(String(50), nullable=False)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("submission_batches.id", ondelete="SET NULL"), nullable=True)
    batch_page_id: Mapped[int | None] = mapped_column(ForeignKey("batch_pages.id", ondelete="SET NULL"), nullable=True)
    image_storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_model: Mapped[str] = mapped_column(String(255), nullable=False)
    ocr_raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ocr_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_reason: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False)
    reporter_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ground_truth_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    redact_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(nullable=True)

    exam: Mapped[Exam | None] = relationship()
    submission: Mapped[Submission | None] = relationship()
    batch: Mapped[SubmissionBatch | None] = relationship()
    batch_page: Mapped[BatchPage | None] = relationship()
```

Also import `datetime` at top of `entities.py`:

```python
from datetime import datetime
```

Update `backend/app/models/__init__.py` to import and export `OcrBadCase`.

- [ ] **Step 8: Create schemas**

Create `backend/app/schemas/bad_case.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import BaseSchema

BadCaseRouteKey = Literal["vision_split_header", "vision_student_extraction", "vision_rubric", "vision_roster"]
BadCaseStatus = Literal["pending", "triaged", "ready", "exported", "discarded"]
BadCaseTriggerSource = Literal["auto", "manual"]


class BadCaseCreate(BaseSchema):
    image_storage_path: str
    route_key: BadCaseRouteKey
    reporter_note: str | None = None
    exam_id: int | None = None
    submission_id: int | None = None
    batch_id: int | None = None
    batch_page_id: int | None = None


class BadCaseUpdate(BaseSchema):
    ground_truth_text: str | None = None
    status: BadCaseStatus | None = None
    redact_pii: bool | None = None
    reporter_note: str | None = None


class BadCaseRead(BaseSchema):
    id: int
    route_key: str
    exam_id: int | None
    submission_id: int | None
    batch_id: int | None
    batch_page_id: int | None
    image_storage_path: str
    image_hash: str
    ocr_model: str
    ocr_raw_text: str
    ocr_error_message: str | None
    trigger_reason: str
    trigger_source: str
    reporter_note: str | None
    ground_truth_text: str | None
    status: str
    redact_pii: bool
    last_seen_at: datetime
    exported_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BadCaseListResponse(BaseSchema):
    items: list[BadCaseRead]
    total: int
    page: int
    page_size: int


class BadCaseStatsItem(BaseSchema):
    route_key: str
    status: str
    count: int


class BadCaseRedactionPreview(BaseSchema):
    id: int
    preview_storage_path: str
    redaction_method: str
    redaction_failed: bool
```

- [ ] **Step 9: Run model/config tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_config.py backend/tests/test_bad_cases.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

Run:

```bash
git add backend/alembic/versions/0009_add_ocr_bad_cases.py backend/app/models/entities.py backend/app/models/__init__.py backend/app/core/config.py backend/app/schemas/bad_case.py backend/tests/test_config.py backend/tests/test_bad_cases.py
git commit -m "Add OCR bad case data model"
```

---

## Task 2: Backend bad-case service layer and state machine

**Files:**
- Create/Modify: `backend/app/services/bad_cases.py`
- Test: `backend/tests/test_bad_cases.py`

- [ ] **Step 1: Write failing service tests**

Append these tests to `backend/tests/test_bad_cases.py`:

```python
from app.services import bad_cases


def test_enqueue_inserts_and_deduplicates_by_image_hash_and_route(session) -> None:
    first_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="b" * 64,
        exam_id=None,
    )
    second_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="new text",
        ocr_error_message="later error",
        trigger_reason="ocr_request_failed",
        image_hash="b" * 64,
        exam_id=None,
    )

    assert second_id == first_id
    stored = session.get(OcrBadCase, first_id)
    assert stored.ocr_raw_text == "new text"
    assert stored.ocr_error_message == "later error"
    assert stored.trigger_reason == "ocr_request_failed"


def test_enqueue_swallows_db_failures(monkeypatch: pytest.MonkeyPatch, session) -> None:
    def fail_flush() -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(session, "flush", fail_flush)

    result = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="c" * 64,
    )

    assert result is None


def test_update_bad_case_auto_triages_when_ground_truth_first_set(session) -> None:
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="d" * 64,
    )

    updated = bad_cases.update_bad_case(session, case_id, ground_truth_text="姓名 张三 学号 123456")

    assert updated.status == "triaged"
    assert updated.ground_truth_text == "姓名 张三 学号 123456"


def test_update_bad_case_rejects_ready_without_ground_truth(session) -> None:
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="e" * 64,
    )

    with pytest.raises(bad_cases.BadCaseError, match="ground_truth_text"):
        bad_cases.update_bad_case(session, case_id, status="ready")
```

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py -q
```

Expected: FAIL because `app.services.bad_cases` is missing.

- [ ] **Step 3: Implement service layer**

Create `backend/app/services/bad_cases.py` with:

```python
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OcrBadCase

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
        existing = session.execute(
            select(OcrBadCase).where(
                OcrBadCase.image_hash == image_hash,
                OcrBadCase.route_key == route_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.trigger_reason = trigger_reason
            existing.last_seen_at = now
            existing.ocr_raw_text = ocr_raw_text or ""
            existing.ocr_error_message = ocr_error_message
            if trigger_source == "manual":
                existing.trigger_source = "manual"
                existing.reporter_note = _append_reporter_note(existing.reporter_note, reporter_note)
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
    except Exception as exc:  # noqa: BLE001 - bad-case collection must not block OCR workflows
        logger.warning("Failed to enqueue OCR bad case route=%s image=%s: %s", route_key, image_storage_path, exc)
        session.rollback()
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
    if search:
        pattern = f"%{search.strip()}%"
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
        stmt.order_by(OcrBadCase.last_seen_at.desc(), OcrBadCase.id.desc()).offset((page - 1) * page_size).limit(page_size)
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


def stats(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        select(OcrBadCase.route_key, OcrBadCase.status, func.count(OcrBadCase.id)).group_by(OcrBadCase.route_key, OcrBadCase.status)
    ).all()
    return [(str(route_key), str(status), int(count)) for route_key, status, count in rows]


def _append_reporter_note(existing: str | None, new_note: str | None) -> str | None:
    normalized = (new_note or "").strip()
    if not normalized:
        return existing
    if not existing:
        return normalized
    return f"{existing}\n{normalized}"
```

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add backend/app/services/bad_cases.py backend/tests/test_bad_cases.py
git commit -m "Add OCR bad case service state machine"
```

---

## Task 3: OCR cache regions and automatic enqueue hooks

**Files:**
- Modify: `backend/app/services/ocr.py`
- Modify: `backend/app/services/batch_pipeline.py`
- Modify: `backend/app/services/pipeline.py`
- Modify: `backend/app/services/roster.py`
- Test: `backend/tests/test_ocr.py`
- Test: `backend/tests/test_batch_pipeline.py`

- [ ] **Step 1: Write failing OCR cache/regions tests**

Extend `backend/tests/test_ocr.py`:

```python
def test_parse_paddle_jsonl_extracts_regions_from_bbox_like_payload() -> None:
    text = json.dumps(
        {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {"text": "姓名 张三 学号 123456"},
                        "prunedResult": {
                            "layoutParsingResults": [
                                {"text": "姓名 张三", "bbox": [10, 20, 110, 50]},
                                {"text": "学号 123456", "box": [[10, 60], [160, 60], [160, 90], [10, 90]]},
                            ]
                        },
                    }
                ]
            }
        }
    )

    pages = parse_paddle_jsonl(text)

    assert pages[0].regions[0].text == "姓名 张三"
    assert pages[0].regions[0].bbox == [10, 20, 110, 50]
    assert pages[0].regions[1].bbox == [10, 60, 160, 90]


def test_cached_text_reads_missing_regions_as_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-image")
    cache_dir = settings.storage_dir / "ocr-cache"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / f"{ocr.hash_file(image_path)}.json"
    cache_path.write_text(json.dumps({"provider": "paddle", "model": settings.paddle_ocr_model, "text": "cached"}), encoding="utf-8")
    try:
        cached = ocr.read_cached_ocr_result(image_path)
    finally:
        get_storage_service.cache_clear()

    assert cached is not None
    assert cached.text == "cached"
    assert cached.regions == []
```

- [ ] **Step 2: Run OCR tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_ocr.py::test_parse_paddle_jsonl_extracts_regions_from_bbox_like_payload backend/tests/test_ocr.py::test_cached_text_reads_missing_regions_as_empty -q
```

Expected: FAIL because `OCRPageText` has no `regions` and `read_cached_ocr_result` is missing.

- [ ] **Step 3: Implement OCRRegion and cache result support**

In `backend/app/services/ocr.py`:

- Add dataclasses:

```python
@dataclass(slots=True)
class OCRRegion:
    text: str
    bbox: list[int]


@dataclass(slots=True)
class CachedOCRResult:
    text: str
    regions: list[OCRRegion]
```

- Extend `OCRPageText`:

```python
regions: list[OCRRegion] | None = None
```

- Add `read_cached_ocr_result(image_path: Path, page_hash: str | None = None) -> CachedOCRResult | None` that reads the same cache path and returns empty regions for old cache files.
- Change `_read_cached_text` to delegate to `read_cached_ocr_result` or split into `_read_cached_result(cache_path)`.
- Change `_write_cached_text` to accept `regions: list[OCRRegion] | None = None` and write a `regions` JSON array.
- Change `PaddleOCRClient.extract_image_text` to combine parsed page regions into the returned `OCRPageText`.
- Change `parse_paddle_jsonl` to attach regions with robust extraction from nested dicts. Use helper functions:

```python
def _extract_regions(value: Any) -> list[OCRRegion]:
    regions: list[OCRRegion] = []
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("recText") or "").strip()
        bbox = _bbox_from_value(value.get("bbox") or value.get("box") or value.get("poly") or value.get("polygon"))
        if text and bbox:
            regions.append(OCRRegion(text=text, bbox=bbox))
        for nested in value.values():
            regions.extend(_extract_regions(nested))
    elif isinstance(value, list):
        for item in value:
            regions.extend(_extract_regions(item))
    return regions


def _bbox_from_value(value: Any) -> list[int] | None:
    if isinstance(value, list) and len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        x1, y1, x2, y2 = value
        return [int(x1), int(y1), int(x2), int(y2)]
    if isinstance(value, list) and value and all(isinstance(point, list) and len(point) >= 2 for point in value):
        xs = [float(point[0]) for point in value]
        ys = [float(point[1]) for point in value]
        return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
    return None
```

- [ ] **Step 4: Run OCR region tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_ocr.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing automatic enqueue tests**

Extend `backend/tests/test_batch_pipeline.py` with a test that monkeypatches `batch_pipeline.bad_cases.enqueue` and calls `_extract_single_header_for_auto_split` with OCR reject reason:

```python
def test_auto_split_header_enqueues_rejected_ocr_bad_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    crop = tmp_path / "header.png"
    page = tmp_path / "page.png"
    crop.write_bytes(b"crop")
    page.write_bytes(b"page")
    calls: list[dict] = []
    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: batch_pipeline.HeaderOCRDiagnostic(text="姓名 张三", reason="ocr_text_extracted", text_chars=5, cache_hit=False))
    monkeypatch.setattr(batch_pipeline, "_header_extraction_from_ocr_text", lambda *_args, **_kwargs: batch_pipeline.PageHeaderExtraction())
    monkeypatch.setattr(batch_pipeline, "call_structured_json", lambda **_kwargs: SimpleNamespace(data=batch_pipeline.PageHeaderExtraction(), raw_text="vision"))
    monkeypatch.setattr(batch_pipeline.bad_cases, "enqueue", lambda _session=None, **kwargs: calls.append(kwargs) or 1)

    result = batch_pipeline._extract_single_header_for_auto_split(
        batch_pipeline.RenderedHeaderCrop(page_no=1, page_image_path=page, crop_path=crop, extracted_text="")
    )

    assert result.page_no == 1
    assert calls[0]["route_key"] == "vision_split_header"
    assert calls[0]["trigger_reason"] == "regex_no_identity"
    assert calls[0]["image_storage_path"].endswith("header.png")
```

Add `from types import SimpleNamespace` if missing.

- [ ] **Step 6: Run enqueue test and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_batch_pipeline.py::test_auto_split_header_enqueues_rejected_ocr_bad_case -q
```

Expected: FAIL because no enqueue is called.

- [ ] **Step 7: Implement automatic enqueue hooks**

In `backend/app/services/batch_pipeline.py`:

- Import `app.services.bad_cases as bad_cases`.
- After `ocr_acceptance_reason` is computed and before returning, call `bad_cases.enqueue` when reason is one of:

```python
BADCASE_HEADER_REASONS = {
    "regex_no_identity",
    "regex_no_student_name",
    "regex_no_student_id",
    "ocr_low_confidence",
    "ocr_empty_text",
    "ocr_request_failed",
}
```

- Because `_extract_single_header_for_auto_split` runs outside a DB session and before `BatchPage` exists, the minimal safe implementation should enqueue after `BatchPage` rows are created in `_prepare_auto_split_batch`, where `batch.id`, `batch.exam_id`, and each `BatchPage.id` are available. Store the OCR reason in `HeaderExtractionResult` first by adding `ocr_acceptance_reason`, `ocr_raw_text`, and `ocr_error_message` fields. Then in `_prepare_auto_split_batch`, after `session.flush()`, enqueue for each rejected extraction with:

```python
bad_cases.enqueue(
    session,
    route_key="vision_split_header",
    image_storage_path=storage.relative_path_for(extraction.crop_path),
    ocr_raw_text=extraction.ocr_raw_text or "",
    ocr_error_message=extraction.ocr_error_message,
    trigger_reason=extraction.ocr_acceptance_reason,
    image_hash=hash_file(extraction.crop_path),
    exam_id=batch.exam_id,
    batch_id=batch.id,
    batch_page_id=batch_page.id,
)
```

- Update tests to exercise the session-level `_prepare_auto_split_batch` path if needed. Do not create a global DB session inside worker threads.

For `_best_text_for_page`:

- Change signature to accept `route_key: str`, `image_storage_path: str | None = None`, `image_hash: str | None = None`, and optional context IDs.
- In `build_ocr_reference_text`, pass `route_key` to `_best_text_for_page`.
- On `OCRError` or empty OCR text, enqueue with `trigger_reason` `ocr_request_failed` or `ocr_empty_text` when image storage path is known.
- Keep DB-write failures swallowed by `bad_cases.enqueue`.

- [ ] **Step 8: Run backend OCR/batch tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_ocr.py backend/tests/test_batch_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add backend/app/services/ocr.py backend/app/services/batch_pipeline.py backend/app/services/pipeline.py backend/app/services/roster.py backend/tests/test_ocr.py backend/tests/test_batch_pipeline.py
git commit -m "Collect OCR bad cases from PaddleOCR failures"
```

---

## Task 4: Redaction service and ZIP export

**Files:**
- Create/Modify: `backend/app/services/bad_cases_redact.py`
- Modify: `backend/app/services/bad_cases.py`
- Test: `backend/tests/test_bad_cases_redact.py`
- Test: `backend/tests/test_bad_cases.py`

- [ ] **Step 1: Write failing redaction tests**

Create `backend/tests/test_bad_cases_redact.py`:

```python
from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.bad_cases_redact import OCRRegion, find_pii_bboxes, redact_image


def test_find_pii_bboxes_detects_student_id_and_labelled_name() -> None:
    regions = [
        OCRRegion(text="姓名 张三", bbox=[10, 10, 90, 40]),
        OCRRegion(text="学号 12345678", bbox=[10, 50, 160, 80]),
        OCRRegion(text="答案", bbox=[10, 90, 60, 120]),
    ]

    boxes = find_pii_bboxes(regions)

    assert [10, 10, 90, 40] in boxes
    assert [10, 50, 160, 80] in boxes


def test_redact_image_blacks_detected_bbox(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out.png"
    Image.new("RGB", (200, 120), "white").save(source)

    result = redact_image(source, "vision_student_extraction", [OCRRegion(text="学号 12345678", bbox=[10, 10, 60, 40])], output)

    assert result.success is True
    assert result.method == "ocr_bbox"
    with Image.open(output) as image:
        assert image.getpixel((20, 20)) == (0, 0, 0)
        assert image.getpixel((100, 100)) == (255, 255, 255)


def test_split_header_redaction_skips_image(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out.png"
    Image.new("RGB", (100, 60), "white").save(source)

    result = redact_image(source, "vision_split_header", [OCRRegion(text="学号 12345678", bbox=[1, 1, 50, 20])], output)

    assert result.success is True
    assert result.method == "no_pii_detected"
    with Image.open(output) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)
```

- [ ] **Step 2: Run redaction tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases_redact.py -q
```

Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement redaction service**

Create `backend/app/services/bad_cases_redact.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import settings
from app.services.ocr import OCRRegion

BBox = list[int]


@dataclass(slots=True)
class RedactionResult:
    method: str
    success: bool


def find_pii_bboxes(regions: list[OCRRegion], *, exam=None, submission=None) -> list[BBox]:
    known_names = {submission.student_name for submission in [submission] if submission is not None and submission.student_name}
    known_ids = {submission.student_id for submission in [submission] if submission is not None and submission.student_id}
    if exam is not None:
        for entry in getattr(exam, "roster_entries", []) or []:
            if entry.student_name:
                known_names.add(entry.student_name)
            if entry.student_id:
                known_ids.add(entry.student_id)
    boxes: list[BBox] = []
    for region in regions:
        text = region.text.strip()
        if not text:
            continue
        if re.search(r"\b\d{6,12}\b", text) or any(student_id and student_id in text for student_id in known_ids):
            boxes.append(region.bbox)
            continue
        if any(name and name in text for name in known_names):
            boxes.append(region.bbox)
            continue
        if re.search(r"(?:姓名|学生|Name)\s*[:：]?\s*[一-鿿]{2,4}", text, flags=re.IGNORECASE):
            boxes.append(region.bbox)
            continue
        if re.search(r"(?:学号|学籍号|考号|student\s*id)\s*[:：]?", text, flags=re.IGNORECASE):
            boxes.append(region.bbox)
    return boxes


def redact_image(
    image_path: Path,
    route_key: str,
    regions: list[OCRRegion],
    out_path: Path,
    *,
    exam=None,
    submission=None,
) -> RedactionResult:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as image:
            redacted = image.convert("RGB")
            if route_key == "vision_split_header":
                redacted.save(out_path)
                return RedactionResult(method="no_pii_detected", success=True)
            boxes = find_pii_bboxes(regions, exam=exam, submission=submission)
            draw = ImageDraw.Draw(redacted)
            if boxes:
                for box in boxes:
                    draw.rectangle(tuple(box), fill=(0, 0, 0))
                method = "ocr_bbox"
            else:
                method = "no_pii_detected"
            redacted.save(out_path)
            return RedactionResult(method=method, success=True)
    except Exception:
        return RedactionResult(method="skipped_image", success=False)


def create_placeholder_image(source_path: Path, out_path: Path, case_id: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source_path) as source:
            size = source.size
    except Exception:
        size = (800, 600)
    image = Image.new("RGB", size, (128, 128, 128))
    draw = ImageDraw.Draw(image)
    draw.text((20, max(20, size[1] // 2)), f"REDACTION FAILED - id: {case_id}", fill=(255, 255, 255))
    image.save(out_path)
```

- [ ] **Step 4: Run redaction tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases_redact.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing ZIP export tests**

Append to `backend/tests/test_bad_cases.py`:

```python
import io
import json
import zipfile
from PIL import Image


def test_export_badcases_zip_writes_jsonl_images_and_marks_exported(session, tmp_path: Path) -> None:
    monkey_storage = settings.storage_dir
    storage_dir = monkey_storage
    image_path = storage_dir / "rendered/submissions/1/pages/page-001.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 80), "white").save(image_path)
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_student_extraction",
        image_storage_path="rendered/submissions/1/pages/page-001.png",
        ocr_raw_text="姓名 张三 学号 12345678",
        ocr_error_message=None,
        trigger_reason="ocr_empty_text",
        image_hash="f" * 64,
    )
    bad_cases.update_bad_case(session, case_id, ground_truth_text="正确文本", status="ready")

    payload, meta = bad_cases.export_badcases_zip(session)

    assert meta["exported_count"] == 1
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        row = json.loads(archive.read("cases.jsonl").decode("utf-8").strip())
        assert row["id"] == case_id
        assert row["schema_version"] == 1
        assert row["ground_truth_text"] == "正确文本"
        assert archive.read(f"images/{case_id:05d}.png")
    assert session.get(OcrBadCase, case_id).status == "exported"
```

- [ ] **Step 6: Run ZIP test and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py::test_export_badcases_zip_writes_jsonl_images_and_marks_exported -q
```

Expected: FAIL because `export_badcases_zip` is missing.

- [ ] **Step 7: Implement export service**

In `backend/app/services/bad_cases.py`, add `export_badcases_zip(session, route_key=None, since_id=None) -> tuple[bytes, dict[str, int]]` that:

- Selects ready cases with non-empty `ground_truth_text`.
- Enforces `settings.badcase_export_max_cases`, raising `BadCaseError` with a message containing `BADCASE_EXPORT_MAX_CASES` if exceeded.
- Writes `README.md`, `cases.jsonl`, and `images/{id:05d}.png` into an in-memory zip.
- Uses `get_storage_service().path_for(case.image_storage_path)` to load images.
- Reads cached OCR regions with `read_cached_ocr_result`; old/no cache means `regions=[]`.
- Calls `redact_image` when `case.redact_pii` is true; for failure uses `create_placeholder_image` and marks `redaction_failed=True`.
- For `redact_pii=False`, copies the source image but still hashes context fields in JSONL.
- Sets `status="exported"` and `exported_at=now` for included cases and commits after ZIP creation.
- Returns metadata keys `exported_count` and `redaction_failed_count`.

- [ ] **Step 8: Run export tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py backend/tests/test_bad_cases_redact.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

Run:

```bash
git add backend/app/services/bad_cases.py backend/app/services/bad_cases_redact.py backend/tests/test_bad_cases.py backend/tests/test_bad_cases_redact.py
git commit -m "Add OCR bad case redaction export"
```

---

## Task 5: Backend bad-case API endpoints and storage validation

**Files:**
- Create: `backend/app/api/bad_cases.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/files.py`
- Test: `backend/tests/test_bad_cases_api.py`
- Test: `backend/tests/test_files_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_bad_cases_api.py` with a TestClient fixture modeled after `backend/tests/test_files_api.py`, then add:

```python
def test_post_badcase_rejects_unreferenced_path(client) -> None:
    test_client, _session, storage = client
    stored = storage.save_text("rendered/unknown/page.png", "image")

    response = test_client.post(
        "/api/badcases",
        json={"image_storage_path": stored.relative_path, "route_key": "vision_split_header"},
    )

    assert response.status_code == 400
    assert "referenced" in response.text


def test_post_badcase_creates_manual_case_for_referenced_path(client) -> None:
    test_client, session, storage = client
    stored = storage.save_text("rendered/submissions/1/pages/page-001.png", "image")
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(exam_id=exam.id, original_pdf_path="submissions/1.pdf")
    session.add(submission)
    session.flush()
    session.add(SubmissionPage(submission_id=submission.id, page_no=1, image_path=stored.relative_path, page_hash="a" * 64))
    session.commit()

    response = test_client.post(
        "/api/badcases",
        json={
            "image_storage_path": stored.relative_path,
            "route_key": "vision_student_extraction",
            "exam_id": exam.id,
            "submission_id": submission.id,
            "reporter_note": "OCR 错字",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trigger_source"] == "manual"
    assert payload["trigger_reason"] == "manual_report"
    assert payload["reporter_note"] == "OCR 错字"


def test_put_badcase_ready_without_ground_truth_returns_400(client) -> None:
    test_client, session, storage = client
    stored = storage.save_text("rendered/submissions/1/pages/page-001.png", "image")
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_student_extraction",
        image_storage_path=stored.relative_path,
        ocr_raw_text="",
        ocr_error_message=None,
        trigger_reason="manual_report",
        trigger_source="manual",
        image_hash="b" * 64,
    )
    session.commit()

    response = test_client.put(f"/api/badcases/{case_id}", json={"status": "ready"})

    assert response.status_code == 400
    assert "ground_truth_text" in response.text
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases_api.py -q
```

Expected: FAIL because router does not exist.

- [ ] **Step 3: Implement API router**

Create `backend/app/api/bad_cases.py`:

- `POST /badcases`: validate storage path via `_storage_path_is_referenced`; hash the file; read cached OCR text when present; call `bad_cases.enqueue(... trigger_source="manual", trigger_reason="manual_report")`; return `BadCaseRead`.
- `GET /badcases`: call `list_bad_cases`; return `BadCaseListResponse`.
- `GET /badcases/{id}`: return `BadCaseRead`.
- `PUT /badcases/{id}`: call `update_bad_case`, map `BadCaseError` to 400/404 based on message.
- `DELETE /badcases/{id}`: hard delete, return `APIMessage` or 204.
- `POST /badcases/{id}/redact-preview`: generate preview image under `badcase-previews/{id}.png`, return `BadCaseRedactionPreview`.
- `GET /badcases/{id}/redact-preview.png`: return preview file via `FileResponse`; validate id first.
- `POST /badcases/export.zip`: wrap `bad_cases.export_badcases_zip` in `with export_slot()`, return `Response` with headers `Content-Disposition`, `X-Exported-Count`, `X-Redaction-Failed-Count`; map busy to 429, limit to 413, missing regions threshold to 409.
- `GET /badcases/stats`: return `list[BadCaseStatsItem]`.

Register in `backend/app/api/router.py`:

```python
from app.api.bad_cases import router as bad_cases_router
api_router.include_router(bad_cases_router)
```

- [ ] **Step 4: Extend storage reference validation**

Modify `backend/app/api/files.py`:

- Import `OcrBadCase`.
- Add `select(literal(1)).where(OcrBadCase.image_storage_path == target)` to `_storage_path_is_referenced`.
- Add support for `badcase-previews/{id}.png` only through the new preview GET endpoint, not general storage, unless it is stored as `image_storage_path`.

- [ ] **Step 5: Run API/storage tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases_api.py backend/tests/test_files_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add backend/app/api/bad_cases.py backend/app/api/router.py backend/app/api/files.py backend/tests/test_bad_cases_api.py backend/tests/test_files_api.py
git commit -m "Add OCR bad case admin API"
```

---

## Task 6: Frontend types, API client, and helper tests

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/badcases.ts`
- Test: `frontend/tests/badcases.test.ts`

- [ ] **Step 1: Write failing frontend helper tests**

Create `frontend/tests/badcases.test.ts`:

```typescript
import assert from 'node:assert/strict'

import { badCaseKey, buildBadCaseQuery } from '../src/lib/badcases'

assert.equal(badCaseKey('rendered/submissions/1/pages/page-001.png', 'vision_student_extraction'), 'vision_student_extraction::rendered/submissions/1/pages/page-001.png')
assert.equal(
  buildBadCaseQuery({ status: 'ready', route_key: 'vision_roster', search: '张三', page: 2, page_size: 25 }),
  '?route_key=vision_roster&status=ready&search=%E5%BC%A0%E4%B8%89&page=2&page_size=25',
)
assert.equal(buildBadCaseQuery({}), '')
```

- [ ] **Step 2: Run helper test and verify RED**

Run:

```bash
node --import tsx frontend/tests/badcases.test.ts
```

If `tsx` is not installed, add a simple package script or use `npx tsx frontend/tests/badcases.test.ts` after confirming availability. Expected: FAIL because `frontend/src/lib/badcases.ts` is missing.

- [ ] **Step 3: Implement frontend types and helpers**

In `frontend/src/lib/types.ts`, add:

```typescript
export type BadCaseRouteKey = 'vision_split_header' | 'vision_student_extraction' | 'vision_rubric' | 'vision_roster'
export type BadCaseStatus = 'pending' | 'triaged' | 'ready' | 'exported' | 'discarded'
export type BadCaseTriggerSource = 'auto' | 'manual'

export interface BadCase {
  id: number
  route_key: BadCaseRouteKey
  exam_id: number | null
  submission_id: number | null
  batch_id: number | null
  batch_page_id: number | null
  image_storage_path: string
  image_hash: string
  ocr_model: string
  ocr_raw_text: string
  ocr_error_message: string | null
  trigger_reason: string
  trigger_source: BadCaseTriggerSource
  reporter_note: string | null
  ground_truth_text: string | null
  status: BadCaseStatus
  redact_pii: boolean
  last_seen_at: string
  exported_at: string | null
  created_at: string
  updated_at: string
}

export interface BadCaseListResponse {
  items: BadCase[]
  total: number
  page: number
  page_size: number
}

export interface BadCaseCreatePayload {
  image_storage_path: string
  route_key: BadCaseRouteKey
  reporter_note?: string | null
  exam_id?: number | null
  submission_id?: number | null
  batch_id?: number | null
  batch_page_id?: number | null
}

export interface BadCaseUpdatePayload {
  ground_truth_text?: string | null
  status?: BadCaseStatus | null
  redact_pii?: boolean | null
  reporter_note?: string | null
}

export interface BadCaseStatsItem {
  route_key: BadCaseRouteKey
  status: BadCaseStatus
  count: number
}
```

Create `frontend/src/lib/badcases.ts`:

```typescript
import type { BadCaseRouteKey, BadCaseStatus } from './types'

export interface BadCaseFilters {
  route_key?: BadCaseRouteKey | ''
  status?: BadCaseStatus | ''
  search?: string
  page?: number
  page_size?: number
}

export function badCaseKey(imageStoragePath: string, routeKey: BadCaseRouteKey): string {
  return `${routeKey}::${imageStoragePath}`
}

export function buildBadCaseQuery(filters: BadCaseFilters): string {
  const params = new URLSearchParams()
  if (filters.route_key) params.set('route_key', filters.route_key)
  if (filters.status) params.set('status', filters.status)
  if (filters.search?.trim()) params.set('search', filters.search.trim())
  if (filters.page !== undefined) params.set('page', String(filters.page))
  if (filters.page_size !== undefined) params.set('page_size', String(filters.page_size))
  const text = params.toString()
  return text ? `?${text}` : ''
}
```

- [ ] **Step 4: Add API client methods**

In `frontend/src/lib/api.ts`, import new types and add:

```typescript
export async function listBadCases(filters: BadCaseFilters = {}): Promise<BadCaseListResponse> {
  return request<BadCaseListResponse>(`/badcases${buildBadCaseQuery(filters)}`)
}

export async function getBadCase(id: number): Promise<BadCase> {
  return request<BadCase>(`/badcases/${id}`)
}

export async function createBadCase(payload: BadCaseCreatePayload): Promise<BadCase> {
  return request<BadCase>('/badcases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateBadCase(id: number, payload: BadCaseUpdatePayload): Promise<BadCase> {
  return request<BadCase>(`/badcases/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function deleteBadCase(id: number): Promise<void> {
  return request<void>(`/badcases/${id}`, { method: 'DELETE' })
}

export async function previewBadCaseRedaction(id: number): Promise<{ id: number; preview_storage_path: string; redaction_method: string; redaction_failed: boolean }> {
  return request(`/badcases/${id}/redact-preview`, { method: 'POST' })
}

export async function exportBadCasesZip(filters: Pick<BadCaseFilters, 'route_key'> = {}): Promise<Blob> {
  return fetchBlob(`/badcases/export.zip${buildBadCaseQuery(filters)}`)
}

export async function getBadCaseStats(): Promise<BadCaseStatsItem[]> {
  return request<BadCaseStatsItem[]>('/badcases/stats')
}
```

- [ ] **Step 5: Run frontend helper/typecheck and verify GREEN**

Run:

```bash
npx tsx frontend/tests/badcases.test.ts
npm --prefix frontend run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/badcases.ts frontend/tests/badcases.test.ts
git commit -m "Add frontend bad case API helpers"
```

---

## Task 7: Frontend admin page and drawer

**Files:**
- Create: `frontend/src/pages/BadCasesPage.tsx`
- Create: `frontend/src/components/BadCaseDrawer.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`

- [ ] **Step 1: Write a failing typecheck-oriented page skeleton test**

No DOM test framework exists. The failing signal for this task is TypeScript import resolution. First add imports/routes before creating the page:

```tsx
// frontend/src/App.tsx
import { BadCasesPage } from './pages/BadCasesPage'
```

Add route:

```tsx
<Route path="/badcases" element={<BadCasesPage />} />
```

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: FAIL because `BadCasesPage` is missing.

- [ ] **Step 2: Implement `BadCaseDrawer`**

Create `frontend/src/components/BadCaseDrawer.tsx` with props:

```typescript
interface BadCaseDrawerProps {
  badCase: BadCase | null
  busy?: boolean
  onClose: () => void
  onSave: (payload: BadCaseUpdatePayload) => Promise<void>
  onPreview: () => Promise<void>
  onDelete: () => Promise<void>
}
```

Required UI:
- Right-side fixed drawer when `badCase !== null`.
- `AuthenticatedImage` for `badCase.image_storage_path`.
- Read-only OCR raw text textarea.
- Editable `ground_truth_text` textarea with save button.
- Editable `reporter_note` textarea.
- `redact_pii` checkbox.
- Buttons for `标记 ready`, `丢弃`, `重置为 ready` when exported, `预览脱敏`, and `删除`.
- `标记 ready` calls `onSave({ status: 'ready', ground_truth_text: draftGroundTruth, reporter_note: draftNote, redact_pii: draftRedact })`.

- [ ] **Step 3: Implement `BadCasesPage`**

Create `frontend/src/pages/BadCasesPage.tsx`:

- Load `listBadCases(filters)` and `getBadCaseStats()` on mount and when filters change.
- Render KPI chips for statuses `pending`, `triaged`, `ready`, `exported`, `discarded`.
- Render filters: status select, route_key select, search input.
- Render table columns: `id`, `route_key`, `trigger_reason`, `status`, `last_seen_at`.
- Click row opens drawer by setting selected `BadCase`.
- Export button calls `exportBadCasesZip({ route_key })`, then `downloadBlob(blob, 'ocr-badcases.zip')`.
- Use existing `SectionCard`, `InlineMessage`-style local component, and `toClassNames` conventions.

- [ ] **Step 4: Add nav entry**

In `frontend/src/components/AppShell.tsx`, add:

```typescript
{ to: '/badcases', label: 'Bad Cases' }
```

- [ ] **Step 5: Run frontend typecheck and verify GREEN**

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add frontend/src/pages/BadCasesPage.tsx frontend/src/components/BadCaseDrawer.tsx frontend/src/App.tsx frontend/src/components/AppShell.tsx
git commit -m "Add OCR bad case admin page"
```

---

## Task 8: Frontend manual report buttons in review pages

**Files:**
- Create: `frontend/src/components/BadCaseReportButton.tsx`
- Modify: `frontend/src/pages/SubmissionReviewPage.tsx`
- Modify: `frontend/src/pages/SubmissionUploadPage.tsx`
- Modify: `frontend/src/pages/RubricReviewPage.tsx`
- Modify: `frontend/src/pages/RosterPage.tsx`

- [ ] **Step 1: Write failing typecheck import**

Import `BadCaseReportButton` into `SubmissionReviewPage.tsx` before creating it:

```typescript
import { BadCaseReportButton } from '../components/BadCaseReportButton'
```

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: FAIL because component is missing.

- [ ] **Step 2: Implement reusable report button**

Create `frontend/src/components/BadCaseReportButton.tsx`:

- Props:

```typescript
interface BadCaseReportButtonProps {
  imageStoragePath: string
  routeKey: BadCaseRouteKey
  examId?: number | null
  submissionId?: number | null
  batchId?: number | null
  batchPageId?: number | null
  compact?: boolean
}
```

- UI behavior:
  - Button label defaults to `报告 OCR`.
  - Opens lightweight modal with one textarea `reporter_note`.
  - On submit calls `createBadCase`.
  - After success sets local state `reported=true` and shows `已上报`.
  - If request fails, show inline error in modal.

- [ ] **Step 3: Integrate into `SubmissionReviewPage`**

In the page thumbnail/rendered page area, place `BadCaseReportButton` for each `SubmissionPage` with:

```tsx
<BadCaseReportButton
  imageStoragePath={page.image_path}
  routeKey="vision_student_extraction"
  examId={submission.exam_id}
  submissionId={submission.id}
  compact
/>
```

- [ ] **Step 4: Integrate into `SubmissionUploadPage`**

For combined-auto split review pages/candidates, add `BadCaseReportButton` where `BatchPage.image_path` or header crop storage path is known:

```tsx
<BadCaseReportButton
  imageStoragePath={page.image_path}
  routeKey="vision_split_header"
  examId={numericExamId}
  batchId={batch.id}
  batchPageId={page.id}
  compact
/>
```

If the UI only has full-page image paths, use full-page `BatchPage.image_path`; do not invent a header crop path on the frontend.

- [ ] **Step 5: Integrate into `RubricReviewPage` and `RosterPage`**

Current frontend does not receive rendered page image paths for rubric/roster pages. Implement this minimally:

- For the latest PDF file, derive rendered paths only after backend parse has populated `page_count`:

```typescript
function renderedExamFilePagePath(examId: number, kind: 'rubric' | 'roster', fileId: number, pageNo: number): string {
  return `rendered/exams/${examId}/${kind}/${fileId}/page-${String(pageNo).padStart(3, '0')}.png`
}
```

- Add report buttons next to page links/previews only when `file.page_count` is non-null.
- Use `routeKey="vision_rubric"` for rubric and `routeKey="vision_roster"` for roster.
- Backend `POST /badcases` must validate this convention against the owning `ExamFile`, not general `_storage_path_is_referenced`, otherwise these derived paths will be rejected.

- [ ] **Step 6: Run frontend typecheck and verify GREEN**

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

Run:

```bash
git add frontend/src/components/BadCaseReportButton.tsx frontend/src/pages/SubmissionReviewPage.tsx frontend/src/pages/SubmissionUploadPage.tsx frontend/src/pages/RubricReviewPage.tsx frontend/src/pages/RosterPage.tsx
git commit -m "Add OCR report buttons to review pages"
```

---

## Task 9: End-to-end backend verification and frontend smoke check

**Files:**
- May modify any files from Tasks 1-8 only to fix verified issues.

- [ ] **Step 1: Run backend targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_bad_cases.py backend/tests/test_bad_cases_api.py backend/tests/test_bad_cases_redact.py backend/tests/test_ocr.py backend/tests/test_batch_pipeline.py backend/tests/test_files_api.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend checks**

Run:

```bash
npx tsx frontend/tests/badcases.test.ts
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 4: Start backend and frontend for manual UI smoke**

Start backend:

```bash
DATABASE_URL=sqlite:///./dev-badcases.db STORAGE_DIR=./storage .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Start frontend:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1
```

Use browser to verify:
- `/badcases` loads under the app shell.
- Filters render.
- Empty state renders.
- Drawer opens if a case exists.
- Report button modal opens on at least one review page with available image paths.

- [ ] **Step 5: Run final git status review**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intended files changed; no PDFs, browser logs, storage outputs, `.venv`, `node_modules`, or generated ZIPs are tracked.

- [ ] **Step 6: Commit final fixes if any**

If Step 1-5 required fixes, commit only those fixes:

```bash
git add <specific fixed files>
git commit -m "Stabilize OCR bad case workflow"
```

---

## Self-Review

- **Spec coverage:** The plan covers the `ocr_bad_cases` table, auto/manual collection, admin API, redaction preview/export, ZIP JSONL/images format, config fields, OCR cache regions, frontend admin page, review-page report buttons, backend pytest, frontend typecheck, and manual smoke testing.
- **Intentional scope control:** The design mentions querying existing reports for each page to initialize checkmarks; this plan starts with local optimistic `已上报` state and admin list. Add a follow-up endpoint if product requires page-level prefetch checkmarks before launch.
- **Known implementation caveat:** Current rubric/roster rendered images are not stored as DB rows. The API must explicitly validate `rendered/exams/{exam_id}/{rubric|roster}/{exam_file_id}/page-NNN.png` against `ExamFile.page_count` and file existence for manual reports.
- **Placeholder scan:** No task uses TBD or unspecified implementation. Each production-code step has a preceding failing-test step.
- **Type consistency:** Backend uses `route_key`, `status`, `trigger_source`, and `image_storage_path` consistently across ORM, schemas, service, API, and frontend DTOs.
