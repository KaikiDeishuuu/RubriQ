from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import (
    Answer,
    AnswerRubricResult,
    ConfidenceLevel,
    Exam,
    ExamFile,
    Question,
    RubricItem,
    Submission,
    SubmissionPage,
    SubmissionStatus,
)
from app.schemas.ai import ExtractedQuestion, GradingResult, RubricParseResult, StudentExtractionResult
from app.services.llm import call_structured_json
from app.services.pdf import RenderedPage, hash_file, render_pdf_to_images
from app.storage.local import get_storage_service
from app.utils.score import clamp_score

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


@dataclass(slots=True)
class RubricItemSnapshot:
    id: int
    description: str
    max_score: Decimal


@dataclass(slots=True)
class QuestionSnapshot:
    id: int
    question_no: str
    title: str
    max_score: Decimal
    rubric_items: list[RubricItemSnapshot]


_CONFIDENCE_RANK = {
    ConfidenceLevel.high: 3,
    ConfidenceLevel.medium: 2,
    ConfidenceLevel.low: 1,
}


def _to_decimal(value: float | int | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _question_payload(question: Question, *, include_keywords: bool = False) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for rubric_item in question.rubric_items:
        item: dict[str, Any] = {
            "id": rubric_item.id,
            "description": rubric_item.description,
            "max_score": float(rubric_item.max_score),
        }
        if include_keywords:
            item["keywords"] = rubric_item.keywords
        items.append(item)
    return {
        "question_no": question.question_no,
        "title": question.title,
        "max_score": float(question.max_score),
        "rubric_items": items,
    }


def _snapshot_question(question: Question) -> QuestionSnapshot:
    return QuestionSnapshot(
        id=question.id,
        question_no=question.question_no,
        title=question.title,
        max_score=_to_decimal(question.max_score),
        rubric_items=[
            RubricItemSnapshot(
                id=rubric_item.id,
                description=rubric_item.description,
                max_score=_to_decimal(rubric_item.max_score),
            )
            for rubric_item in question.rubric_items
        ],
    )


def _combine_confidence(*levels: ConfidenceLevel | str | None) -> ConfidenceLevel:
    normalized: list[ConfidenceLevel] = []
    for level in levels:
        if level is None:
            continue
        if isinstance(level, ConfidenceLevel):
            normalized.append(level)
            continue
        try:
            normalized.append(ConfidenceLevel(level))
        except ValueError:
            normalized.append(ConfidenceLevel.low)
    if not normalized:
        return ConfidenceLevel.low
    return min(normalized, key=lambda item: _CONFIDENCE_RANK[item])


def _load_exam(session: Session, exam_id: int) -> Exam:
    stmt = (
        select(Exam)
        .where(Exam.id == exam_id)
        .options(
            selectinload(Exam.files),
            selectinload(Exam.questions).selectinload(Question.rubric_items),
        )
    )
    exam = session.execute(stmt).scalar_one_or_none()
    if exam is None:
        raise PipelineError(f"Exam {exam_id} not found")
    return exam


def _load_submission(session: Session, submission_id: int) -> Submission:
    stmt = (
        select(Submission)
        .where(Submission.id == submission_id)
        .options(
            selectinload(Submission.exam)
            .selectinload(Exam.questions)
            .selectinload(Question.rubric_items),
            selectinload(Submission.pages),
            selectinload(Submission.answers)
            .selectinload(Answer.question)
            .selectinload(Question.rubric_items),
            selectinload(Submission.answers).selectinload(Answer.rubric_results),
        )
    )
    submission = session.execute(stmt).scalar_one_or_none()
    if submission is None:
        raise PipelineError(f"Submission {submission_id} not found")
    return submission


def _latest_exam_file(exam: Exam, file_type: str) -> ExamFile:
    candidates = [exam_file for exam_file in exam.files if exam_file.file_type == file_type]
    if not candidates:
        raise PipelineError(f"No exam file of type {file_type} found")
    return sorted(candidates, key=lambda item: item.created_at)[-1]


def _render_pdf_assets(storage_root: Path, relative_pdf_path: str, scope: str) -> list[RenderedPage]:
    storage = get_storage_service()
    pdf_path = storage.path_for(relative_pdf_path)
    if not pdf_path.exists():
        raise PipelineError(f"PDF not found at {relative_pdf_path}")
    output_dir = storage_root / scope
    return render_pdf_to_images(pdf_path, output_dir, dpi=settings.render_dpi)


def parse_rubric_for_exam(session: Session, exam_id: int, exam_file_id: int | None = None) -> Exam:
    exam = _load_exam(session, exam_id)
    exam_file = _pick_exam_file(exam, exam_file_id, "rubric_pdf")
    storage = get_storage_service()
    pdf_path = storage.path_for(exam_file.storage_path)
    if not pdf_path.exists():
        raise PipelineError("Rubric PDF no longer exists")

    rendered_pages = render_pdf_to_images(
        pdf_path,
        storage.path_for(f"rendered/exams/{exam.id}/rubric/{exam_file.id}"),
        dpi=settings.render_dpi,
    )
    prompt_variables = {
        "exam_title": exam.title,
        "teacher_notes": exam.description or "",
    }
    try:
        completion = call_structured_json(
            model=settings.ai_vision_model,
            system_prompt_name="rubric_extraction.system.md",
            user_prompt_name="rubric_extraction.user.md",
            response_model=RubricParseResult,
            prompt_variables=prompt_variables,
            image_paths=[page.image_path for page in rendered_pages],
            request_profile="vision",
        )
    except Exception as exc:  # noqa: BLE001 - rubric parsing should surface a user-visible failure
        exam_file.error_message = str(exc)
        session.commit()
        raise PipelineError(f"Rubric parsing failed: {exc}") from exc

    extracted_questions = _scored_questions_only(completion.data.questions)
    _replace_exam_questions(session, exam.id)
    exam = _load_exam(session, exam.id)
    for order_index, question_payload in enumerate(extracted_questions):
        question = Question(
            exam_id=exam.id,
            question_no=question_payload.question_no,
            title=question_payload.title,
            max_score=_to_decimal(question_payload.max_score),
            order_index=order_index,
        )
        session.add(question)
        session.flush()
        for rubric_index, rubric_payload in enumerate(question_payload.rubric_items):
            session.add(
                RubricItem(
                    question_id=question.id,
                    description=rubric_payload.description,
                    max_score=_to_decimal(rubric_payload.max_score),
                    keywords=rubric_payload.keywords,
                    order_index=rubric_index,
                )
            )

    exam.total_score = _to_decimal(
        sum(float(question.max_score) for question in extracted_questions)
    )
    exam.needs_rubric_review = True
    exam_file.page_count = len(rendered_pages)
    exam_file.parsed_json = RubricParseResult(questions=extracted_questions).model_dump(mode="json")
    exam_file.raw_ai_response = completion.raw_text
    exam_file.error_message = None
    session.commit()
    return _load_exam(session, exam.id)


def process_submission(session: Session, submission_id: int) -> Submission:
    submission = _load_submission(session, submission_id)
    exam = submission.exam
    storage = get_storage_service()
    pdf_path = storage.path_for(submission.original_pdf_path)
    if not pdf_path.exists():
        raise PipelineError("Submission PDF no longer exists")

    submission.status = SubmissionStatus.processing.value
    session.commit()

    submission.status = SubmissionStatus.rendering.value
    session.commit()

    rendered_pages = render_pdf_to_images(
        pdf_path,
        storage.path_for(f"rendered/submissions/{submission.id}/pages"),
        dpi=settings.render_dpi,
    )
    _replace_submission_pages(session, submission.id)
    for rendered_page in rendered_pages:
        session.add(
            SubmissionPage(
                submission_id=submission.id,
                page_no=rendered_page.page_no,
                image_path=storage.relative_path_for(rendered_page.image_path),
                page_hash=hash_file(rendered_page.image_path),
                extracted_text=rendered_page.extracted_text,
                raw_ai_response=None,
            )
        )
    session.flush()

    submission.status = SubmissionStatus.extracting.value
    session.commit()

    question_reference_json = json.dumps(
        [_question_payload(question, include_keywords=True) for question in exam.questions],
        ensure_ascii=False,
        indent=2,
    )

    extraction_result, extraction_raw_response = _extract_submission_answers(
        exam_title=exam.title,
        questions_json=question_reference_json,
        image_paths=[page.image_path for page in rendered_pages],
    )
    if not submission.student_name:
        submission.student_name = extraction_result.student_name
    if not submission.student_id:
        submission.student_id = extraction_result.student_id
    submission.raw_extraction_response = extraction_raw_response
    submission.error_message = None

    extracted_by_question = {
        answer.question_no: answer for answer in extraction_result.answers
    }
    _replace_submission_answers(session, submission.id)
    session.flush()
    submission.status = SubmissionStatus.grading.value
    session.commit()

    running_total = Decimal("0")
    any_needs_review = False

    grading_tasks = []
    for question in exam.questions:
        extracted_answer = extracted_by_question.get(question.question_no)
        answer_text = (extracted_answer.answer_text or "").strip() if extracted_answer else ""
        source_page = extracted_answer.source_page if extracted_answer else None
        extraction_confidence = extracted_answer.confidence if extracted_answer else ConfidenceLevel.low
        grading_tasks.append(
            (
                submission.id,
                _snapshot_question(question),
                answer_text,
                source_page,
                extraction_confidence,
            )
        )

    max_workers = min(len(grading_tasks), settings.ai_grading_concurrency)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _grade_question,
                submission_id=sid,
                question=q,
                answer_text=at,
                source_page=sp,
                extraction_confidence=ec,
            ): q
            for sid, q, at, sp, ec in grading_tasks
        }
        for future in as_completed(futures):
            answer, rubric_results, answer_needs_review = future.result()
            session.add(answer)
            session.flush()
            for rubric_result in rubric_results:
                rubric_result.answer_id = answer.id
                session.add(rubric_result)
            running_total += answer.teacher_override_score if answer.teacher_override_score is not None else answer.score
            any_needs_review = any_needs_review or answer_needs_review
            submission.total_score = _to_decimal(running_total)
            submission.status = SubmissionStatus.grading.value
            session.commit()

    submission.total_score = _to_decimal(running_total)
    submission.status = (
        SubmissionStatus.needs_review.value if any_needs_review else SubmissionStatus.graded.value
    )
    session.commit()
    return _load_submission(session, submission.id)


def apply_teacher_override(
    session: Session,
    answer_id: int,
    teacher_override_score: float | None,
    teacher_comment: str | None,
) -> Answer:
    answer = session.get(Answer, answer_id)
    if answer is None:
        raise PipelineError(f"Answer {answer_id} not found")
    answer.teacher_override_score = (
        _to_decimal(teacher_override_score) if teacher_override_score is not None else None
    )
    answer.teacher_comment = teacher_comment
    session.flush()
    _recalculate_submission_total(session, answer.submission_id)
    session.commit()
    updated_answer = session.execute(
        select(Answer)
        .where(Answer.id == answer_id)
        .options(selectinload(Answer.question).selectinload(Question.rubric_items), selectinload(Answer.rubric_results))
    ).scalar_one()
    return updated_answer


def _grade_question(
    *,
    submission_id: int,
    question: QuestionSnapshot,
    answer_text: str,
    source_page: int | None,
    extraction_confidence: ConfidenceLevel,
) -> tuple[Answer, list[AnswerRubricResult], bool]:
    started_at = time.perf_counter()
    used_fallback = False
    if not answer_text.strip():
        used_fallback = True
        answer, rubric_results, needs_review = _build_empty_answer_fallback(
            submission_id=submission_id,
            question=question,
            source_page=source_page,
        )
        logger.info(
            "Question grading completed submission_id=%s question_id=%s question_no=%s model=%s duration_seconds=%.2f fallback=%s",
            submission_id,
            question.id,
            question.question_no,
            settings.ai_grading_model,
            time.perf_counter() - started_at,
            used_fallback,
        )
        return answer, rubric_results, needs_review

    grading_input = _build_grading_input(question, answer_text)

    try:
        strictness = settings.ai_grading_strictness
        strictness_instructions = _strictness_instructions(strictness)
        completion = call_structured_json(
            model=settings.ai_grading_model,
            system_prompt_name="grading.system.md",
            user_prompt_name="grading.user.md",
            response_model=GradingResult,
            prompt_variables={
                "grading_input_json": json.dumps(grading_input, ensure_ascii=False, indent=2),
                "strictness": strictness,
                "strictness_instructions": strictness_instructions,
            },
            request_profile="grading",
        )
        grading_result = completion.data
        raw_response = completion.raw_text
    except Exception as exc:  # noqa: BLE001 - we want a safe fallback for grading
        used_fallback = True
        logger.exception("Question grading failed for question %s: %s", question.id, exc)
        grading_result = None
        raw_response = f"ERROR: {exc}"
    finally:
        logger.info(
            "Question grading completed submission_id=%s question_id=%s question_no=%s model=%s duration_seconds=%.2f fallback=%s",
            submission_id,
            question.id,
            question.question_no,
            settings.ai_grading_model,
            time.perf_counter() - started_at,
            used_fallback,
        )

    if grading_result is None:
        return _build_error_fallback(
            submission_id=submission_id,
            question=question,
            answer_text=answer_text,
            source_page=source_page,
            extraction_confidence=extraction_confidence,
            raw_response=raw_response,
        )

    rubric_results = []
    rubric_lookup = {rubric_item.id: rubric_item for rubric_item in question.rubric_items}
    awarded_total = Decimal("0")
    missing_points = list(grading_result.missing_points)
    rubric_item_ids_seen: set[int] = set()

    for evaluation in grading_result.rubric_evaluation:
        rubric_item_id = _coerce_int(evaluation.rubric_item_id)
        rubric_item = rubric_lookup.get(rubric_item_id)
        if rubric_item is None:
            continue
        awarded_score = _to_decimal(
            clamp_score(
                float(evaluation.awarded_score),
                0.0,
                float(rubric_item.max_score),
            )
        )
        awarded_total += awarded_score
        rubric_item_ids_seen.add(rubric_item.id)
        rubric_results.append(
            AnswerRubricResult(
                rubric_item_id=rubric_item.id,
                awarded_score=awarded_score,
                evidence=evaluation.evidence_from_student_answer.strip(),
                reason=evaluation.reason.strip(),
            )
        )

    for rubric_item in question.rubric_items:
        if rubric_item.id in rubric_item_ids_seen:
            continue
        rubric_results.append(
            AnswerRubricResult(
                rubric_item_id=rubric_item.id,
                awarded_score=Decimal("0"),
                evidence="",
                reason="AI 未返回该评分项的评分证据，按 0 分处理并建议人工复核。",
            )
        )
        if rubric_item.description not in missing_points:
            missing_points.append(rubric_item.description)

    final_score = _to_decimal(
        clamp_score(float(awarded_total), 0.0, float(question.max_score))
    )
    if answer_text.strip():
        min_score_ratio = 0.15 if settings.ai_grading_strictness == "lenient" else 0.05
        min_score = _to_decimal(float(question.max_score) * min_score_ratio)
        if min_score < Decimal("0.5"):
            min_score = Decimal("0.5")
        final_score = max(final_score, min_score)
    final_confidence = _combine_confidence(extraction_confidence, grading_result.confidence)
    needs_review = bool(
        grading_result.needs_human_review
        or final_confidence == ConfidenceLevel.low
        or not answer_text.strip()
    )
    if needs_review and grading_result.final_comment.strip() and grading_result.final_comment.strip() not in missing_points:
        missing_points.append(grading_result.final_comment.strip())

    answer = Answer(
        submission_id=submission_id,
        question_id=question.id,
        source_page=source_page,
        extracted_answer=answer_text,
        score=final_score,
        max_score=_to_decimal(question.max_score),
        confidence=final_confidence.value,
        ai_comment=grading_result.final_comment.strip(),
        missing_points=_dedupe_strings(missing_points),
        needs_human_review=needs_review,
        teacher_override_score=None,
        teacher_comment=None,
        raw_ai_response=raw_response,
    )
    return answer, rubric_results, needs_review


def _build_grading_input(question: QuestionSnapshot, answer_text: str) -> dict[str, Any]:
    return {
        "question_no": question.question_no,
        "question": question.title,
        "max_score": float(question.max_score),
        "rubric_items": [
            {
                "id": rubric_item.id,
                "description": rubric_item.description,
                "max_score": float(rubric_item.max_score),
            }
            for rubric_item in question.rubric_items
        ],
        "student_answer": answer_text,
    }


def _strictness_instructions(strictness: str) -> str:
    return {
        "lenient": """Grade generously against the answer-template rubric. Rules:
1. ONLY assess against the provided rubric items — do NOT penalize for concepts not listed in the rubric.
2. Treat semantic equivalence as correct: if the student's wording means the same thing as the rubric item, award credit even if it uses different terms, order, symbols, or Chinese-English phrasing.
3. NEVER give 0 to a rubric item unless the student wrote nothing for that question or the answer is entirely unrelated to that rubric item.
4. If the student attempted a relevant answer for a rubric item, award at least 50% of that item's max_score.
5. If the student addresses ANY meaningful part of a rubric item's description, award at least 70% of that item's max_score.
6. If the student covers the main idea of a rubric item with minor omissions or imprecise wording, award at least 80% of that item's max_score.
7. Award full credit when the answer matches the rubric's core meaning, even if it is shorter than the template answer.
8. Give the benefit of the doubt for ambiguous phrasing, informal wording, OCR artifacts, or mixed Chinese-English.
9. Mark missing_points ONLY for rubric item concepts that are completely absent or clearly contradicted by the student's answer.
10. If a rubric item has multiple sub-points and the student covers at least one, award proportional credit generously (e.g., 2 sub-points, 1 covered = 60%+ score).
11. The final_comment should be encouraging and note what the student did well, not just what was missed.""",
        "moderate": """Grade fairly. Rules:
1. Assess against the provided rubric items only — do not add extra requirements.
2. NEVER give 0 to a rubric item unless the student wrote nothing for that question. If the student attempted an answer, award at least 20% of the item's max_score.
3. Award partial credit proportional to how much of the rubric item the student's answer covers.
4. Mark missing_points for rubric item concepts that are missing or substantially incorrect.
5. Balance strictness with fairness — if the student shows understanding but expresses it poorly, still award some credit.""",
        "strict": """Grade strictly. Rules:
1. Assess against the provided rubric items precisely.
2. Award credit only when the student's answer explicitly and accurately matches the rubric item.
3. Require key terminology and complete reasoning as specified in the rubric.
4. Mark missing_points for any part of the rubric item that is missing or incorrect.
5. Even in strict mode, do not give 0 unless the student left the answer blank.""",
    }.get(strictness, "")


def _build_empty_answer_fallback(
    *,
    submission_id: int,
    question: QuestionSnapshot,
    source_page: int | None,
) -> tuple[Answer, list[AnswerRubricResult], bool]:
    rubric_results = [
        AnswerRubricResult(
            rubric_item_id=rubric_item.id,
            awarded_score=Decimal("0"),
            evidence="",
            reason="未识别到该题的学生答案文本，需要人工复核。",
        )
        for rubric_item in question.rubric_items
    ]
    answer = Answer(
        submission_id=submission_id,
        question_id=question.id,
        source_page=source_page,
        extracted_answer="",
        score=Decimal("0"),
        max_score=_to_decimal(question.max_score),
        confidence=ConfidenceLevel.low.value,
        ai_comment="未从答卷中识别到该题答案文本，需要人工复核。",
        missing_points=[rubric_item.description for rubric_item in question.rubric_items],
        needs_human_review=True,
        teacher_override_score=None,
        teacher_comment=None,
        raw_ai_response="",
    )
    return answer, rubric_results, True


def _build_error_fallback(
    *,
    submission_id: int,
    question: QuestionSnapshot,
    answer_text: str,
    source_page: int | None,
    extraction_confidence: ConfidenceLevel,
    raw_response: str,
) -> tuple[Answer, list[AnswerRubricResult], bool]:
    error_detail = raw_response.replace("ERROR: ", "").strip()
    rubric_results = [
        AnswerRubricResult(
            rubric_item_id=rubric_item.id,
            awarded_score=Decimal("0"),
            evidence="",
            reason=f"AI 评分失败：{error_detail}",
        )
        for rubric_item in question.rubric_items
    ]
    answer = Answer(
        submission_id=submission_id,
        question_id=question.id,
        source_page=source_page,
        extracted_answer=answer_text,
        score=Decimal("0"),
        max_score=_to_decimal(question.max_score),
        confidence=_combine_confidence(extraction_confidence, ConfidenceLevel.low).value,
        ai_comment="AI 评分失败，需要人工复核。",
        missing_points=[rubric_item.description for rubric_item in question.rubric_items],
        needs_human_review=True,
        teacher_override_score=None,
        teacher_comment=None,
        raw_ai_response=raw_response,
    )
    return answer, rubric_results, True


def _extract_submission_answers(
    *,
    exam_title: str,
    questions_json: str,
    image_paths: list[Path],
) -> tuple[StudentExtractionResult, str]:
    try:
        completion = call_structured_json(
            model=settings.ai_vision_model,
            system_prompt_name="student_extraction.system.md",
            user_prompt_name="student_extraction.user.md",
            response_model=StudentExtractionResult,
            prompt_variables={
                "exam_title": exam_title,
                "questions_json": questions_json,
            },
            image_paths=image_paths,
            request_profile="vision",
        )
        return completion.data, completion.raw_text
    except Exception as exc:  # noqa: BLE001 - fall back to an empty extraction result for manual review
        logger.exception("Student extraction failed; falling back to empty answers")
        return StudentExtractionResult(student_name=None, student_id=None, answers=[]), f"ERROR: {exc}"


def _scored_questions_only(questions: list[ExtractedQuestion]) -> list[ExtractedQuestion]:
    question_numbers = {question.question_no.strip() for question in questions}
    scored_questions: list[ExtractedQuestion] = []
    for question in questions:
        question_no = question.question_no.strip()
        has_child_questions = any(
            other_no != question_no and other_no.startswith(f"{question_no}.")
            for other_no in question_numbers
        )
        if has_child_questions and not question.rubric_items:
            continue
        scored_questions.append(question)
    return scored_questions


def _replace_exam_questions(session: Session, exam_id: int) -> None:
    orphaned_answer_count = session.execute(
        select(func.count()).select_from(Answer).where(
            Answer.question_id.in_(select(Question.id).where(Question.exam_id == exam_id))
        )
    ).scalar_one()
    if orphaned_answer_count > 0:
        raise PipelineError(
            f"Exam {exam_id} has {orphaned_answer_count} existing graded answer(s). "
            "Re-parsing the rubric would cascade-delete them. "
            "Delete the submissions first or create a new exam."
        )
    session.execute(
        delete(RubricItem).where(
            RubricItem.question_id.in_(select(Question.id).where(Question.exam_id == exam_id))
        )
    )
    session.execute(delete(Question).where(Question.exam_id == exam_id))
    session.flush()


def _replace_submission_pages(session: Session, submission_id: int) -> None:
    session.execute(delete(SubmissionPage).where(SubmissionPage.submission_id == submission_id))
    session.flush()


def _replace_submission_answers(session: Session, submission_id: int) -> None:
    session.execute(
        delete(AnswerRubricResult).where(
            AnswerRubricResult.answer_id.in_(select(Answer.id).where(Answer.submission_id == submission_id))
        )
    )
    session.execute(delete(Answer).where(Answer.submission_id == submission_id))
    session.flush()


def _recalculate_submission_total(session: Session, submission_id: int) -> None:
    submission = _load_submission(session, submission_id)
    total = Decimal("0")
    any_review = False
    for answer in submission.answers:
        effective_score = answer.teacher_override_score if answer.teacher_override_score is not None else answer.score
        total += effective_score
        any_review = any_review or answer.needs_human_review or answer.confidence == ConfidenceLevel.low.value
    submission.total_score = _to_decimal(total)
    submission.status = (
        SubmissionStatus.needs_review.value if any_review else SubmissionStatus.graded.value
    )
    session.flush()


def _pick_exam_file(exam: Exam, exam_file_id: int | None, file_type: str) -> ExamFile:
    if exam_file_id is not None:
        for exam_file in exam.files:
            if exam_file.id == exam_file_id:
                return exam_file
        raise PipelineError(f"Exam file {exam_file_id} not found")
    return _latest_exam_file(exam, file_type)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped

