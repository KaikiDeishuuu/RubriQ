from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Answer, ConfidenceLevel, Exam, Question, Submission
from app.services.pipeline import _to_decimal


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


def build_exam_results_pdf(session: Session, exam_id: int) -> bytes:
    data = build_exam_results_data(session, exam_id)
    exam = data["exam"]
    questions = data["questions"]
    rows = data["rows"]
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"{exam.title} results",
    )
    title_style = ParagraphStyle(
        "ResultTitle",
        fontName="STSong-Light",
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "ResultMeta",
        fontName="STSong-Light",
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
    )
    cell_style = ParagraphStyle(
        "ResultCell",
        fontName="STSong-Light",
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
    )
    center_cell_style = ParagraphStyle(
        "ResultCenterCell",
        parent=cell_style,
        alignment=TA_CENTER,
    )
    header_cell_style = ParagraphStyle(
        "ResultHeaderCell",
        parent=center_cell_style,
        textColor=colors.white,
    )
    story = [
        Paragraph(escape(f"{exam.title} 批量评分结果"), title_style),
        Paragraph(
            escape(
                f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　"
                f"答卷数量：{len(rows)}　题目数量：{len(questions)}"
            ),
            meta_style,
        ),
        Spacer(1, 8),
    ]
    header = ["学生姓名", "学号", "状态", "总分", "复核"] + [f"{question.question_no}" for question in questions]
    table_data: list[list[Any]] = [[_pdf_cell(value, header_cell_style) for value in header]]
    for row in rows:
        question_scores = row["question_scores"]
        table_data.append(
            [
                _pdf_cell(row["student_name"] or "未填写", cell_style),
                _pdf_cell(row["student_id"] or "-", cell_style),
                _pdf_cell(_submission_status_label(row["status"]), center_cell_style),
                _pdf_cell(_format_score(row["total_score"]), center_cell_style),
                _pdf_cell("需要" if row["needs_human_review"] else "否", center_cell_style),
            ]
            + [
                _pdf_cell(_format_score(question_scores.get(question.question_no)), center_cell_style)
                for question in questions
            ]
        )
    table = Table(table_data, repeatRows=1, colWidths=_pdf_column_widths(len(questions)))
    table_style_commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, len(table_data)):
        if row_index % 2 == 0:
            table_style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f9fafb")))
    table.setStyle(TableStyle(table_style_commands))
    story.append(table)
    document.build(story)
    return output.getvalue()


def _pdf_cell(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value)), style)


def _pdf_column_widths(question_count: int) -> list[float]:
    fixed_widths = [34 * mm, 30 * mm, 22 * mm, 18 * mm, 18 * mm]
    if question_count == 0:
        return fixed_widths
    available_width = landscape(A4)[0] - 24 * mm
    question_width = max(10 * mm, (available_width - sum(fixed_widths)) / question_count)
    return fixed_widths + [question_width] * question_count


def _format_score(value: Any) -> str:
    if value is None:
        return "-"
    return str(_to_decimal(value))


def _submission_status_label(status: str) -> str:
    return {
        "uploaded": "已上传",
        "processing": "处理中",
        "rendering": "渲染中",
        "extracting": "识别中",
        "grading": "评分中",
        "graded": "已评分",
        "needs_review": "需复核",
        "failed": "失败",
    }.get(status, status)


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
