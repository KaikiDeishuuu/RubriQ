from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class ExamCreate(BaseSchema):
    title: str
    description: str | None = None


class ExamUpdate(BaseSchema):
    title: str | None = None
    description: str | None = None


class ExamListItem(BaseSchema):
    id: int
    title: str
    description: str | None = None
    total_score: Decimal
    needs_rubric_review: bool
    created_at: datetime
    updated_at: datetime
    question_count: int = 0
    submission_count: int = 0


class ExamFileRead(BaseSchema):
    id: int
    exam_id: int
    file_type: str
    original_filename: str
    storage_path: str
    page_count: int | None = None
    parsed_json: dict[str, Any] | None = None
    raw_ai_response: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RubricItemBase(BaseSchema):
    description: str
    max_score: float
    keywords: list[str] = Field(default_factory=list)
    order_index: int = 0


class RubricItemCreate(RubricItemBase):
    pass


class RubricItemUpdate(BaseSchema):
    description: str | None = None
    max_score: float | None = None
    keywords: list[str] | None = None
    order_index: int | None = None


class RubricItemRead(BaseSchema):
    id: int
    question_id: int
    description: str
    max_score: Decimal
    keywords: list[str] = Field(default_factory=list)
    order_index: int
    created_at: datetime
    updated_at: datetime


class QuestionBase(BaseSchema):
    question_no: str
    title: str
    max_score: float
    order_index: int = 0


class QuestionCreate(QuestionBase):
    pass


class QuestionUpdate(BaseSchema):
    question_no: str | None = None
    title: str | None = None
    max_score: float | None = None
    order_index: int | None = None


class QuestionRead(BaseSchema):
    id: int
    exam_id: int
    question_no: str
    title: str
    max_score: Decimal
    order_index: int
    rubric_items: list[RubricItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExamDetail(BaseSchema):
    id: int
    title: str
    description: str | None = None
    total_score: Decimal
    needs_rubric_review: bool
    created_at: datetime
    updated_at: datetime
    files: list[ExamFileRead] = Field(default_factory=list)
    questions: list[QuestionRead] = Field(default_factory=list)


class ExamResultRow(BaseSchema):
    submission_id: int
    student_name: str | None = None
    student_id: str | None = None
    status: str
    total_score: float
    needs_human_review: bool = False
    source_mode: str | None = None
    split_confidence: float | None = None
    split_confirmed: bool = False
    question_scores: dict[str, float] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExamResultsResponse(BaseSchema):
    exam: ExamDetail
    questions: list[QuestionRead] = Field(default_factory=list)
    rows: list[ExamResultRow] = Field(default_factory=list)
