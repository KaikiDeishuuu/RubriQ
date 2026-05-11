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
