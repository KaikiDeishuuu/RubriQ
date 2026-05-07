from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Answer, ConfidenceLevel, Exam, Question, Submission
from app.services.pipeline import _combine_confidence, _to_decimal


def _effective_answer_score(answer: Answer) -> Decimal:
    return _to_decimal(
        answer.teacher_override_score if answer.teacher_override_score is not None else answer.score
    )


def build_exam_results_data(session: Session, exam_id: int) -> dict[str, Any]:
    exam = _load_exam_for_results(session, exam_id)
    questions = list(exam.questions)
    rows: list[dict[str, Any]] = []
    for submission in exam.submissions:
        row_question_scores: dict[str, float] = {}
        effective_total = Decimal("0")
        needs_review = False
        for answer in submission.answers:
            effective_score = _effective_answer_score(answer)
            row_question_scores[answer.question.question_no] = float(effective_score)
            effective_total += effective_score
            needs_review = needs_review or answer.needs_human_review or answer.confidence == ConfidenceLevel.low.value
        rows.append(
            {
                "submission_id": submission.id,
                "student_name": submission.student_name,
                "student_id": submission.student_id,
                "status": submission.status,
                "total_score": float(_to_decimal(effective_total)),
                "needs_human_review": needs_review,
                "question_scores": row_question_scores,
                "created_at": submission.created_at,
                "updated_at": submission.updated_at,
            }
        )
    return {
        "exam": exam,
        "questions": questions,
        "rows": rows,
    }


def build_exam_results_csv(session: Session, exam_id: int) -> str:
    data = build_exam_results_data(session, exam_id)
    questions = data["questions"]
    rows = data["rows"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = [
        "submission_id",
        "student_name",
        "student_id",
        "status",
        "total_score",
        "needs_human_review",
    ] + [f"question_{question.question_no}_score" for question in questions]
    writer.writerow(header)
    for row in rows:
        question_scores = row["question_scores"]
        writer.writerow(
            [
                row["submission_id"],
                row["student_name"] or "",
                row["student_id"] or "",
                row["status"],
                row["total_score"],
                "yes" if row["needs_human_review"] else "no",
            ]
            + [question_scores.get(question.question_no, 0.0) for question in questions]
        )
    return buffer.getvalue()


def build_exam_results_xlsx(session: Session, exam_id: int) -> bytes:
    data = build_exam_results_data(session, exam_id)
    questions = data["questions"]
    rows = data["rows"]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Results"
    header = [
        "submission_id",
        "student_name",
        "student_id",
        "status",
        "total_score",
        "needs_human_review",
    ] + [f"question_{question.question_no}_score" for question in questions]
    worksheet.append(header)
    for row in rows:
        question_scores = row["question_scores"]
        worksheet.append(
            [
                row["submission_id"],
                row["student_name"],
                row["student_id"],
                row["status"],
                row["total_score"],
                row["needs_human_review"],
            ]
            + [question_scores.get(question.question_no, 0.0) for question in questions]
        )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _load_exam_for_results(session: Session, exam_id: int) -> Exam:
    stmt = (
        select(Exam)
        .where(Exam.id == exam_id)
        .options(
            selectinload(Exam.questions).selectinload(Question.rubric_items),
            selectinload(Exam.submissions)
            .selectinload(Submission.answers)
            .selectinload(Answer.question),
            selectinload(Exam.submissions).selectinload(Submission.answers).selectinload(Answer.rubric_results),
        )
    )
    exam = session.execute(stmt).scalar_one_or_none()
    if exam is None:
        raise ValueError(f"Exam {exam_id} not found")
    return exam
