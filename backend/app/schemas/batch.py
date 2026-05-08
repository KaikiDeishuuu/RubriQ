from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.enums import BatchStatus, BatchUploadMode
from app.schemas.base import BaseSchema
from app.schemas.submission import SubmissionSummary


class BatchPageRead(BaseSchema):
    id: int
    batch_id: int
    page_no: int
    image_path: str
    page_hash: str
    extracted_text: str | None = None
    header_extraction_json: dict[str, Any] | None = None
    raw_ai_response: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class BatchSplitCandidateRead(BaseSchema):
    id: int
    batch_id: int
    candidate_index: int
    start_page: int
    end_page: int
    student_name: str | None = None
    student_id: str | None = None
    split_confidence: float
    needs_review: bool
    review_notes: str | None = None
    confirmed: bool
    excluded: bool = False
    source_filename: str | None = None
    source_storage_path: str | None = None
    error_message: str | None = None
    submission_id: int | None = None
    created_at: datetime
    updated_at: datetime


class BatchDetail(BaseSchema):
    id: int
    exam_id: int
    mode: BatchUploadMode
    status: BatchStatus
    source_filename: str
    source_storage_path: str
    pages_per_submission: int | None = None
    total_pages: int | None = None
    split_version: int
    raw_split_extraction_response: dict[str, Any] | None = None
    error_message: str | None = None
    ai_review_status: str = "not_started"
    ai_review_error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    pages: list[BatchPageRead] = Field(default_factory=list)
    candidates: list[BatchSplitCandidateRead] = Field(default_factory=list)
    submissions: list[SubmissionSummary] = Field(default_factory=list)


class BatchUploadResponse(BaseSchema):
    batch: BatchDetail


class BatchCandidateUpdate(BaseSchema):
    id: int | None = None
    candidate_index: int | None = None
    start_page: int
    end_page: int
    student_name: str | None = None
    student_id: str | None = None
    review_notes: str | None = None
    confirmed: bool = False
    excluded: bool = False


class BatchCandidatesUpdateRequest(BaseSchema):
    candidates: list[BatchCandidateUpdate]


class BatchConfirmResponse(BaseSchema):
    batch: BatchDetail
    created_submission_count: int = 0
    failed_candidate_count: int = 0


class BatchStartGradingResponse(BaseSchema):
    batch_id: int
    queued_submission_count: int
    status: BatchStatus
