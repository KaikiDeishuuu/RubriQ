from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.models.enums import ConfidenceLevel, SubmissionStatus
from app.schemas.base import BaseSchema
from app.schemas.exam import ExamDetail, ExamFileRead, QuestionRead


class SubmissionCreate(BaseSchema):
    student_name: str | None = None
    student_id: str | None = None


class SubmissionSummary(BaseSchema):
    id: int
    exam_id: int
    student_name: str | None = None
    student_id: str | None = None
    original_pdf_path: str
    status: SubmissionStatus
    total_score: Decimal
    raw_extraction_response: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class SubmissionPageRead(BaseSchema):
    id: int
    submission_id: int
    page_no: int
    image_path: str
    extracted_text: str | None = None
    raw_ai_response: str | None = None
    created_at: datetime
    updated_at: datetime


class AnswerRubricResultRead(BaseSchema):
    id: int
    answer_id: int
    rubric_item_id: int
    awarded_score: Decimal
    evidence: str
    reason: str
    created_at: datetime
    updated_at: datetime


class AnswerDetail(BaseSchema):
    id: int
    submission_id: int
    question_id: int
    source_page: int | None = None
    extracted_answer: str
    score: Decimal
    max_score: Decimal
    confidence: ConfidenceLevel
    ai_comment: str | None = None
    missing_points: list[str] = Field(default_factory=list)
    needs_human_review: bool
    teacher_override_score: Decimal | None = None
    teacher_comment: str | None = None
    raw_ai_response: str | None = None
    question: QuestionRead
    rubric_results: list[AnswerRubricResultRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    effective_score: float = 0.0


class SubmissionDetail(SubmissionSummary):
    exam: ExamDetail
    pages: list[SubmissionPageRead] = Field(default_factory=list)
    answers: list[AnswerDetail] = Field(default_factory=list)


class SubmissionOverride(BaseSchema):
    teacher_override_score: float | None = None
    teacher_comment: str | None = None


class SubmissionUploadResponse(BaseSchema):
    submissions: list[SubmissionSummary] = Field(default_factory=list)


class PageUploadResponse(BaseSchema):
    message: str
    exam_file: ExamFileRead | None = None


class ProcessResponse(BaseSchema):
    submission_id: int
    status: SubmissionStatus
