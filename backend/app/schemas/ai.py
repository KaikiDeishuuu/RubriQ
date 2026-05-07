from __future__ import annotations

from pydantic import Field

from app.models.enums import ConfidenceLevel
from app.schemas.base import BaseSchema


class ExtractedRubricItem(BaseSchema):
    description: str
    max_score: float
    keywords: list[str] = Field(default_factory=list)


class ExtractedQuestion(BaseSchema):
    question_no: str
    title: str
    max_score: float
    rubric_items: list[ExtractedRubricItem] = Field(default_factory=list)


class RubricParseResult(BaseSchema):
    questions: list[ExtractedQuestion] = Field(default_factory=list)


class ExtractedStudentAnswer(BaseSchema):
    question_no: str
    answer_text: str | None = None
    source_page: int | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.low


class StudentExtractionResult(BaseSchema):
    student_name: str | None = None
    student_id: str | None = None
    answers: list[ExtractedStudentAnswer] = Field(default_factory=list)


class PageHeaderField(BaseSchema):
    value: str | int | None = None
    confidence: float = 0.0


class PageHeaderExtraction(BaseSchema):
    student_name: PageHeaderField = Field(default_factory=PageHeaderField)
    student_id: PageHeaderField = Field(default_factory=PageHeaderField)
    quiz_title: PageHeaderField = Field(default_factory=PageHeaderField)
    page_number: PageHeaderField = Field(default_factory=PageHeaderField)
    is_first_page_confidence: float = 0.0
    overall_confidence: float = 0.0


class GradingEvaluationItem(BaseSchema):
    rubric_item_id: int | str
    rubric_item: str
    max_item_score: float
    awarded_score: float
    evidence_from_student_answer: str
    reason: str


class GradingResult(BaseSchema):
    score: float
    max_score: float
    confidence: ConfidenceLevel
    rubric_evaluation: list[GradingEvaluationItem] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    final_comment: str
    needs_human_review: bool
