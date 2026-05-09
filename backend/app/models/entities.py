from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BatchStatus, ConfidenceLevel, SubmissionStatus


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
    roster_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_uploaded")
    roster_raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    roster_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    batches: Mapped[list["SubmissionBatch"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="SubmissionBatch.created_at.desc()",
    )
    roster_entries: Mapped[list["RosterEntry"]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="RosterEntry.order_index.asc()",
    )


class SubmissionBatch(Base, TimestampMixin):
    __tablename__ = "submission_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=BatchStatus.uploaded.value)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    pages_per_submission: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    split_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    raw_split_extraction_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    ai_review_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="batches")
    pages: Mapped[list["BatchPage"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="BatchPage.page_no.asc()",
    )
    candidates: Mapped[list["BatchSplitCandidate"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="BatchSplitCandidate.candidate_index.asc()",
    )
    submissions: Mapped[list["Submission"]] = relationship(back_populates="batch")


class BatchPage(Base, TimestampMixin):
    __tablename__ = "batch_pages"
    __table_args__ = (UniqueConstraint("batch_id", "page_no", name="uq_batch_pages_batch_page_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("submission_batches.id", ondelete="CASCADE"), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    page_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_extraction_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped[SubmissionBatch] = relationship(back_populates="pages")


class BatchSplitCandidate(Base, TimestampMixin):
    __tablename__ = "batch_split_candidates"
    __table_args__ = (
        UniqueConstraint("batch_id", "candidate_index", name="uq_batch_candidates_batch_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("submission_batches.id", ondelete="CASCADE"), nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    split_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    roster_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_roster_entries.id", ondelete="SET NULL"),
        nullable=True,
    )

    batch: Mapped[SubmissionBatch] = relationship(back_populates="candidates")
    submission: Mapped["Submission | None"] = relationship(back_populates="batch_candidate", uselist=False)
    roster_entry: Mapped["RosterEntry | None"] = relationship(back_populates="candidates")

    @property
    def submission_id(self) -> int | None:
        return self.submission.id if self.submission is not None else None


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
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("submission_batches.id", ondelete="SET NULL"), nullable=True)
    batch_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("batch_split_candidates.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=SubmissionStatus.uploaded.value)
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    raw_extraction_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    split_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deduction_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    deduction_summary_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    teacher_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    exam: Mapped[Exam] = relationship(back_populates="submissions")
    batch: Mapped[SubmissionBatch | None] = relationship(back_populates="submissions", foreign_keys=[batch_id])
    batch_candidate: Mapped[BatchSplitCandidate | None] = relationship(
        back_populates="submission",
        foreign_keys=[batch_candidate_id],
    )
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
    page_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
    fast_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fast_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fast_ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    fast_missing_points: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    fast_raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    review_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_missing_points: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    review_raw_ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_triggers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_decision: Mapped[str] = mapped_column(String(50), nullable=False, default="not_required")
    review_model: Mapped[str | None] = mapped_column(String(255), nullable=True)

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


class RosterEntry(Base, TimestampMixin):
    __tablename__ = "exam_roster_entries"
    __table_args__ = (
        UniqueConstraint("exam_id", "order_index", name="uq_roster_entries_exam_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    exam: Mapped[Exam] = relationship(back_populates="roster_entries")
    candidates: Mapped[list["BatchSplitCandidate"]] = relationship(back_populates="roster_entry")
