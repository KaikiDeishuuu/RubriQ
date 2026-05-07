from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ConfidenceLevel, SubmissionStatus


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="teacher")


class Exam(Base, TimestampMixin):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    needs_rubric_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    files: Mapped[list["ExamFile"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="ExamFile.created_at.desc()",
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="Question.order_index.asc()",
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="Submission.created_at.desc()",
    )


class ExamFile(Base, TimestampMixin):
    __tablename__ = "exam_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, default="rubric_pdf")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="files")


class Question(Base, TimestampMixin):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    question_no: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    exam: Mapped[Exam] = relationship(back_populates="questions")
    rubric_items: Mapped[list["RubricItem"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="RubricItem.order_index.asc()",
    )


class RubricItem(Base, TimestampMixin):
    __tablename__ = "rubric_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    question: Mapped[Question] = relationship(back_populates="rubric_items")


class Submission(Base, TimestampMixin):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=SubmissionStatus.uploaded.value)
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    raw_extraction_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="submissions")
    pages: Mapped[list["SubmissionPage"]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionPage.page_no.asc()",
    )
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="Answer.id.asc()",
    )


class SubmissionPage(Base, TimestampMixin):
    __tablename__ = "submission_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="pages")


class Answer(Base, TimestampMixin):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default=ConfidenceLevel.low.value)
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    teacher_override_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    teacher_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    rubric_results: Mapped[list["AnswerRubricResult"]] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        order_by="AnswerRubricResult.id.asc()",
    )


class AnswerRubricResult(Base, TimestampMixin):
    __tablename__ = "answer_rubric_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), nullable=False)
    rubric_item_id: Mapped[int] = mapped_column(ForeignKey("rubric_items.id", ondelete="CASCADE"), nullable=False)
    awarded_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    answer: Mapped[Answer] = relationship(back_populates="rubric_results")
    rubric_item: Mapped[RubricItem] = relationship()
