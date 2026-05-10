from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Exam, Question, Submission
from app.schemas.exam import QuestionUpdate, RubricItemCreate
from app.services import pipeline
from app.services.export import ExportLimitError, build_exam_submissions_zip
from app.utils.files import read_upload_limited


@pytest.mark.anyio("asyncio")
async def test_read_upload_limited_rejects_oversized_file() -> None:
    upload = UploadFile(filename="large.pdf", file=BytesIO(b"%PDF-" + b"x" * 10))

    with pytest.raises(Exception) as exc_info:
        await read_upload_limited(upload, 8, too_large_detail="too large", chunk_size=4)

    assert getattr(exc_info.value, "status_code") == 413
    assert getattr(exc_info.value, "detail") == "too large"


def test_score_and_order_schema_validation_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError, match="max_score"):
        RubricItemCreate(description="point", max_score=-1)
    with pytest.raises(ValidationError, match="order_index"):
        QuestionUpdate(order_index=-1)


def test_pipeline_rejects_duplicate_rubric_question_numbers() -> None:
    questions = [
        pipeline.ExtractedQuestion(question_no="1", title="A", max_score=1, rubric_items=[]),
        pipeline.ExtractedQuestion(question_no="1", title="B", max_score=1, rubric_items=[]),
    ]

    with pytest.raises(pipeline.PipelineError, match="duplicate question number"):
        pipeline._ensure_unique_question_numbers(questions)


def test_question_number_db_unique_index_is_case_insensitive() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Sample")
        session.add(exam)
        session.flush()
        session.add(Question(exam_id=exam.id, question_no="Q1", title="Question", max_score=1, order_index=0))
        session.commit()
        session.add(Question(exam_id=exam.id, question_no="q1", title="Duplicate", max_score=1, order_index=1))

        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.close()


def test_submission_zip_export_respects_submission_count_limit(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Sample")
        session.add(exam)
        session.flush()
        session.add(Question(exam_id=exam.id, question_no="1", title="Question", max_score=1, order_index=0))
        session.add(Submission(exam_id=exam.id, original_pdf_path="missing.pdf", status="uploaded"))
        session.commit()
        monkeypatch.setattr("app.services.export.settings.export_submissions_zip_max_submissions", 0)

        with pytest.raises(ExportLimitError):
            build_exam_submissions_zip(session, exam.id)
    finally:
        session.close()
