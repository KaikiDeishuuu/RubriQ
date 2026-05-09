from __future__ import annotations

import csv
import io
import re
import zipfile
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

from app.models import Answer, AnswerRubricResult, Exam, Question, RubricItem, Submission
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
            needs_review = needs_review or answer.needs_human_review
        rows.append(
            {
                "submission_id": submission.id,
                "student_name": submission.student_name,
                "student_id": submission.student_id,
                "status": submission.status,
                "total_score": float(_to_decimal(effective_total)),
                "needs_human_review": needs_review,
                "ai_reviewed_answer_count": sum(1 for answer in submission.answers if answer.review_score is not None),
                "pending_review_answer_count": sum(1 for answer in submission.answers if answer.needs_human_review),
                "source_mode": submission.source_mode,
                "split_confidence": submission.split_confidence,
                "split_confirmed": submission.split_confirmed,
                "question_scores": row_question_scores,
                "created_at": submission.created_at,
                "updated_at": submission.updated_at,
            }
        )
    ai_review_statuses = [batch.ai_review_status for batch in exam.batches if batch.ai_review_status != "not_started"]
    return {
        "exam": exam,
        "questions": questions,
        "rows": rows,
        "ai_review_active": any(status in {"queued", "running"} for status in ai_review_statuses),
        "ai_review_statuses": sorted(set(ai_review_statuses)),
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
        title=f"{exam.title} 成绩与复核结果报告",
    )
    styles = _pdf_styles()
    question_chunks = _chunk_questions(questions, 8) or [[]]
    story = [
        Paragraph(escape(f"{exam.title} 成绩与复核结果报告"), styles["title"]),
        Spacer(1, 4),
        _build_pdf_summary_table(exam, rows, questions, styles),
        Spacer(1, 10),
    ]
    for index, question_chunk in enumerate(question_chunks, start=1):
        story.append(Paragraph(escape(_question_chunk_title(question_chunk, index, len(question_chunks))), styles["section"]))
        story.append(_build_pdf_result_table(rows, question_chunk, questions, styles))
        if index < len(question_chunks):
            story.append(Spacer(1, 10))
    document.build(story)
    return output.getvalue()


def build_submission_review_pdf(session: Session, submission_id: int) -> bytes:
    submission = _load_submission_for_review_pdf(session, submission_id)
    exam = submission.exam
    questions = list(exam.questions)
    answers_by_question_id = {answer.question_id: answer for answer in submission.answers}
    exam_total = sum((_to_decimal(question.max_score) for question in questions), Decimal("0"))
    effective_total = sum((_effective_answer_score(answer) for answer in submission.answers), Decimal("0"))
    needs_review = any(answer.needs_human_review for answer in submission.answers)

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{exam.title} 答卷评分说明",
    )
    styles = _pdf_styles()
    story: list[Any] = [
        Paragraph(escape(f"《{exam.title}》答卷评分说明"), styles["title"]),
        Spacer(1, 4),
        _build_submission_summary_table(submission, effective_total, exam_total, needs_review, styles),
        Spacer(1, 8),
        Paragraph(
            escape("本报告用于核对每道题的评分依据与复核结论。若复核状态为待复核，请以教师最终复核结果为准。"),
            styles["cell"],
        ),
        Spacer(1, 10),
    ]
    deduction_text = _resolve_deduction_summary(submission)
    if deduction_text:
        story.extend(
            [
                Paragraph(escape("扣分摘要" + ("（教师已编辑）" if submission.deduction_summary_edited else "")), styles["section"]),
                _build_deduction_summary_block(deduction_text, styles),
                Spacer(1, 10),
            ]
        )
    for question in questions:
        answer = answers_by_question_id.get(question.id)
        story.extend(_build_submission_question_section(question, answer, styles))
        story.append(Spacer(1, 8))
    if not questions:
        story.append(Paragraph(escape("暂无题目信息，请联系教师确认评分结果。"), styles["cell"]))
    document.build(story)
    return output.getvalue()


def _pdf_styles() -> dict[str, ParagraphStyle]:
    title_style = ParagraphStyle(
        "ResultTitle",
        fontName="STSong-Light",
        fontSize=20,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "ResultSection",
        fontName="STSong-Light",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#111827"),
        spaceAfter=5,
    )
    cell_style = ParagraphStyle(
        "ResultCell",
        fontName="STSong-Light",
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#1f2937"),
    )
    center_cell_style = ParagraphStyle(
        "ResultCenterCell",
        parent=cell_style,
        alignment=TA_CENTER,
    )
    summary_label_style = ParagraphStyle(
        "ResultSummaryLabel",
        parent=center_cell_style,
        textColor=colors.HexColor("#4b5563"),
    )
    summary_value_style = ParagraphStyle(
        "ResultSummaryValue",
        parent=center_cell_style,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#111827"),
    )
    header_cell_style = ParagraphStyle(
        "ResultHeaderCell",
        parent=center_cell_style,
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )
    return {
        "title": title_style,
        "section": section_style,
        "cell": cell_style,
        "center": center_cell_style,
        "summary_label": summary_label_style,
        "summary_value": summary_value_style,
        "header": header_cell_style,
    }


def _build_pdf_summary_table(
    exam: Exam,
    rows: list[dict[str, Any]],
    questions: list[Question],
    styles: dict[str, ParagraphStyle],
) -> Table:
    graded_count = sum(1 for row in rows if row["status"] == "graded")
    review_count = sum(1 for row in rows if row["needs_human_review"])
    total_score = sum((_to_decimal(question.max_score) for question in questions), Decimal("0"))
    summary_items = [
        ("考试名称", exam.title),
        ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("答卷数", str(len(rows))),
        ("已评分", str(graded_count)),
        ("待复核", str(review_count)),
        ("题目数", str(len(questions))),
        ("卷面总分", _format_score(total_score)),
    ]
    table_data = [
        [_pdf_cell(label, styles["summary_label"]) for label, _value in summary_items],
        [_pdf_cell(value, styles["summary_value"]) for _label, value in summary_items],
    ]
    table = Table(table_data, colWidths=[(landscape(A4)[0] - 24 * mm) / len(summary_items)] * len(summary_items))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table



def _build_submission_summary_table(
    submission: Submission,
    effective_total: Decimal,
    exam_total: Decimal,
    needs_review: bool,
    styles: dict[str, ParagraphStyle],
) -> Table:
    summary_items = [
        ("学生姓名", submission.student_name or "未填写"),
        ("学号", submission.student_id or "-"),
        ("答卷状态", _submission_status_label(submission.status)),
        ("总分/满分", _format_score_pair(effective_total, exam_total)),
        ("复核状态", _review_status_label(needs_review)),
        ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]
    table_data = [
        [_pdf_cell(label, styles["summary_label"]) for label, _value in summary_items],
        [_pdf_cell(value, styles["summary_value"]) for _label, value in summary_items],
    ]
    table = Table(table_data, colWidths=[(A4[0] - 32 * mm) / len(summary_items)] * len(summary_items))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _resolve_deduction_summary(submission: Submission) -> str:
    """Return the teacher-edited summary if present, otherwise generate one on the fly."""

    from app.services.pipeline import generate_deduction_summary

    stored = (submission.deduction_summary or "").strip()
    if stored:
        return stored
    return generate_deduction_summary(submission)


def _build_deduction_summary_block(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    safe_html = escape(text).replace("\n", "<br/>")
    paragraph = Paragraph(safe_html, styles["cell"])
    table = Table([[paragraph]], colWidths=[A4[0] - 32 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d97706")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _build_submission_question_section(
    question: Question,
    answer: Answer | None,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    if answer is None:
        return [
            Paragraph(escape(f"题目 {question.question_no}：{question.title}"), styles["section"]),
            _build_submission_question_summary_table(question, None, styles),
            Spacer(1, 4),
            Paragraph(escape("暂无评分明细，请联系教师复核。"), styles["cell"]),
        ]
    content: list[Any] = [
        Paragraph(escape(f"题目 {question.question_no}：{question.title}"), styles["section"]),
        _build_submission_question_summary_table(question, answer, styles),
        Spacer(1, 4),
        Paragraph(escape("作答摘录"), styles["section"]),
        Paragraph(escape(_truncate_text(answer.extracted_answer or "未识别到作答内容。", 700)), styles["cell"]),
        Spacer(1, 4),
        Paragraph(escape("评分依据"), styles["section"]),
        _build_rubric_result_table(question, answer, styles),
    ]
    feedback_items = _submission_feedback_items(answer)
    if feedback_items:
        content.extend([Spacer(1, 4), Paragraph(escape("综合反馈与复核说明"), styles["section"])])
        for label, value in feedback_items:
            content.append(Paragraph(f"<b>{escape(label)}：</b>{escape(value)}", styles["cell"]))
    return content


def _build_submission_question_summary_table(
    question: Question,
    answer: Answer | None,
    styles: dict[str, ParagraphStyle],
) -> Table:
    if answer is None:
        values = [
            ("最终得分/满分", _format_score_pair(None, question.max_score)),
            ("AI 原始得分", "-"),
            ("教师复核得分", "-"),
            ("复核状态", "待复核"),
        ]
    else:
        values = [
            ("最终得分/满分", _format_score_pair(_effective_answer_score(answer), question.max_score)),
            ("快速评分", _format_score_pair(answer.fast_score if answer.fast_score is not None else answer.score, answer.max_score)),
            ("AI 复审", _format_score_pair(answer.review_score, answer.max_score) if answer.review_score is not None else "未触发"),
            ("复核状态", _review_status_label(answer.needs_human_review)),
        ]
    table_data = [
        [_pdf_cell(label, styles["summary_label"]) for label, _value in values],
        [_pdf_cell(value, styles["summary_value"]) for _label, value in values],
    ]
    table = Table(table_data, colWidths=[(A4[0] - 32 * mm) / len(values)] * len(values))
    table.setStyle(TableStyle(_summary_table_style_commands()))
    return table


def _build_rubric_result_table(
    question: Question,
    answer: Answer,
    styles: dict[str, ParagraphStyle],
) -> Table:
    rubric_results = list(answer.rubric_results)
    if not rubric_results:
        table_data = [[_pdf_cell("暂无评分项明细，请联系教师复核。", styles["cell"])]]
        table = Table(table_data, colWidths=[A4[0] - 32 * mm])
        table.setStyle(TableStyle(_plain_box_style_commands()))
        return table
    rubric_items_by_id = {item.id: item for item in question.rubric_items}
    table_data: list[list[Any]] = [[_pdf_cell(value, styles["header"]) for value in ["评分项", "得分/满分", "判断依据", "证据"]]]
    for result in rubric_results:
        rubric_item = rubric_items_by_id.get(result.rubric_item_id)
        table_data.append(
            [
                _pdf_cell(_rubric_item_label(rubric_item, result), styles["cell"]),
                _pdf_cell(_format_score_pair(result.awarded_score, rubric_item.max_score if rubric_item else None), styles["center"]),
                _pdf_cell(result.reason or "暂无判断依据。", styles["cell"]),
                _pdf_cell(result.evidence or "暂无明确证据。", styles["cell"]),
            ]
        )
    table = Table(table_data, repeatRows=1, colWidths=[40 * mm, 24 * mm, 55 * mm, A4[0] - 32 * mm - 119 * mm])
    table.setStyle(TableStyle(_rubric_table_style_commands(len(table_data))))
    return table


def _rubric_item_label(rubric_item: RubricItem | None, result: AnswerRubricResult) -> str:
    if rubric_item is None:
        return f"评分项 #{result.rubric_item_id}"
    return rubric_item.description


def _submission_feedback_items(answer: Answer) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if answer.ai_comment:
        items.append(("评分反馈", answer.ai_comment))
    missing_points = [str(point) for point in (answer.missing_points or []) if str(point).strip()]
    if missing_points:
        items.append(("待改进要点", "；".join(missing_points)))
    review_summary = _answer_review_summary(answer)
    if review_summary:
        items.append(("AI 复审说明", review_summary))
    if answer.teacher_comment:
        items.append(("教师复核说明", answer.teacher_comment))
    return items


def _answer_review_summary(answer: Answer) -> str | None:
    triggers = [format_review_trigger(trigger) for trigger in (answer.review_triggers or [])]
    if answer.review_score is None and not triggers:
        return None
    parts: list[str] = []
    if triggers:
        parts.append(f"触发原因：{'、'.join(triggers)}")
    if answer.review_score is not None:
        parts.append(
            f"强模型复审得分：{_format_score_pair(answer.review_score, answer.max_score)}，最终采用得分：{_format_score_pair(answer.score, answer.max_score)}"
        )
    elif answer.review_decision == "failed":
        parts.append("强模型复审失败，需教师人工复核。")
    return "；".join(parts)


def format_review_trigger(trigger: str) -> str:
    return {
        "low_confidence": "低置信度",
        "model_requested_review": "模型建议复核",
        "missing_rubric_evidence": "评分项证据不足",
        "score_variance": "同题分差较大",
        "score_delta": "快慢模型分差较大",
    }.get(trigger, trigger)


def _summary_table_style_commands() -> list[tuple[Any, ...]]:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]


def _rubric_table_style_commands(row_count: int) -> list[tuple[Any, ...]]:
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#111827")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, row_count):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f9fafb")))
    return commands


def _plain_box_style_commands() -> list[tuple[Any, ...]]:
    return [
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]


def _truncate_text(text: str, max_length: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length]}..."


def _chunk_questions(questions: list[Question], chunk_size: int) -> list[list[Question]]:
    return [questions[index : index + chunk_size] for index in range(0, len(questions), chunk_size)]


def _question_chunk_title(questions: list[Question], index: int, total_chunks: int) -> str:
    if not questions:
        return "成绩明细"
    first_question = questions[0].question_no
    last_question = questions[-1].question_no
    suffix = f"（第 {index}/{total_chunks} 页）" if total_chunks > 1 else ""
    return f"成绩明细：题组 {first_question} 至 {last_question}{suffix}"



def _build_pdf_result_table(
    rows: list[dict[str, Any]],
    questions: list[Question],
    all_questions: list[Question],
    styles: dict[str, ParagraphStyle],
) -> Table:
    header = ["序号", "学生姓名", "学号", "状态", "总分/满分", "复核状态"] + [
        _question_header(question) for question in questions
    ]
    table_data: list[list[Any]] = [[_pdf_cell(value, styles["header"]) for value in header]]
    exam_total = sum((_to_decimal(question.max_score) for question in all_questions), Decimal("0"))
    for row_index, row in enumerate(rows, start=1):
        question_scores = row["question_scores"]
        table_data.append(
            [
                _pdf_cell(str(row_index), styles["center"]),
                _pdf_cell(row["student_name"] or "未填写", styles["cell"]),
                _pdf_cell(row["student_id"] or "-", styles["cell"]),
                _pdf_cell(_submission_status_label(row["status"]), styles["center"]),
                _pdf_cell(_format_score_pair(row["total_score"], exam_total), styles["center"]),
                _pdf_cell(_review_status_label(row["needs_human_review"]), styles["center"]),
            ]
            + [
                _pdf_cell(_format_score_pair(question_scores.get(question.question_no), question.max_score), styles["center"])
                for question in questions
            ]
        )
    table = Table(table_data, repeatRows=1, colWidths=_pdf_column_widths(len(questions)))
    table.setStyle(TableStyle(_pdf_table_style_commands(len(table_data))))
    return table


def _pdf_table_style_commands(row_count: int) -> list[tuple[Any, ...]]:
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#111827")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, row_count):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f9fafb")))
    return commands


def _review_status_label(needs_human_review: bool) -> str:
    return "待复核" if needs_human_review else "已复核"


def _pdf_cell(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value)), style)


def _question_header(question: Question) -> str:
    return f"{question.question_no}\n满分 {_format_score(question.max_score)}"


def _pdf_column_widths(question_count: int) -> list[float]:
    fixed_widths = [12 * mm, 32 * mm, 28 * mm, 20 * mm, 24 * mm, 22 * mm]
    if question_count == 0:
        return fixed_widths
    available_width = landscape(A4)[0] - 24 * mm
    question_width = max(13 * mm, (available_width - sum(fixed_widths)) / question_count)
    return fixed_widths + [question_width] * question_count


def _format_score(value: Any) -> str:
    if value is None:
        return "-"
    decimal_value = _to_decimal(value)
    if decimal_value == decimal_value.to_integral_value():
        return str(decimal_value.to_integral_value())
    return str(decimal_value.normalize())


def _format_score_pair(score: Any, max_score: Any) -> str:
    if score is None:
        return f"-/{_format_score(max_score)}"
    return f"{_format_score(score)}/{_format_score(max_score)}"


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


def _load_submission_for_review_pdf(session: Session, submission_id: int) -> Submission:
    stmt = (
        select(Submission)
        .where(Submission.id == submission_id)
        .options(
            selectinload(Submission.exam)
            .selectinload(Exam.questions)
            .selectinload(Question.rubric_items),
            selectinload(Submission.answers)
            .selectinload(Answer.question)
            .selectinload(Question.rubric_items),
            selectinload(Submission.answers).selectinload(Answer.rubric_results),
        )
    )
    submission = session.execute(stmt).scalar_one_or_none()
    if submission is None:
        raise ValueError(f"Submission {submission_id} not found")
    return submission


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename_segment(value: str | None, fallback: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", (value or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def _submission_pdf_filename(submission: Submission) -> str:
    student_id = _safe_filename_segment(submission.student_id, f"submission-{submission.id}")
    student_name = _safe_filename_segment(submission.student_name, f"id-{submission.id}")
    suffix = "" if submission.status in {"graded", "needs_review"} else "-未评分"
    return f"{student_id}-{student_name}{suffix}.pdf"


def build_exam_submissions_zip(session: Session, exam_id: int) -> tuple[bytes, int, int]:
    """Bundle every submission's review PDF into one ZIP, returns (bytes, total, failures)."""

    exam = _load_exam_for_results(session, exam_id)
    buffer = io.BytesIO()
    failure_count = 0
    used_names: set[str] = set()
    failure_log: list[str] = []
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for submission in exam.submissions:
            try:
                pdf_bytes = build_submission_review_pdf(session, submission.id)
            except Exception as exc:  # noqa: BLE001 - one bad PDF should not abort the whole archive
                failure_count += 1
                failure_log.append(
                    f"submission_id={submission.id} student={submission.student_name or '-'} error={exc}"
                )
                continue
            base_name = _submission_pdf_filename(submission)
            name = base_name
            disambiguator = 2
            while name in used_names:
                stem, ext = base_name.rsplit(".", 1) if "." in base_name else (base_name, "pdf")
                name = f"{stem} ({disambiguator}).{ext}"
                disambiguator += 1
            used_names.add(name)
            archive.writestr(name, pdf_bytes)
        if failure_log:
            archive.writestr(
                "_失败列表.txt",
                "下列答卷生成评分说明 PDF 失败，请到对应复核页面查看：\n\n" + "\n".join(failure_log),
            )
    return buffer.getvalue(), len(exam.submissions), failure_count


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
            selectinload(Exam.batches),
        )
    )
    exam = session.execute(stmt).scalar_one_or_none()
    if exam is None:
        raise ValueError(f"Exam {exam_id} not found")
    return exam
