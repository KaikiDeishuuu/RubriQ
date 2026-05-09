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

from sqlalchemy import delete, func, select, update as sa_update
from sqlalchemy.orm import Session, selectinload

from app.core.config import AIRouteKey, settings
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
from app.services.ocr import build_ocr_reference_text, format_ocr_reference_text
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


@dataclass(slots=True)
class GradingAttempt:
    score: Decimal
    confidence: ConfidenceLevel
    ai_comment: str
    missing_points: list[str]
    raw_response: str
    rubric_results: list[AnswerRubricResult]
    needs_human_review: bool
    model: str
    model_requested_review: bool
    missing_rubric_evidence: bool


_CONFIDENCE_RANK = {
    ConfidenceLevel.high: 3,
    ConfidenceLevel.medium: 2,
    ConfidenceLevel.low: 1,
}


def _to_decimal(value: float | int | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


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


def _review_image_paths_from_rendered_pages(pages: list[RenderedPage], source_page: int | None) -> list[Path]:
    if not pages:
        return []
    if source_page is None:
        return [page.image_path for page in pages]
    selected = [page.image_path for page in pages if abs(page.page_no - source_page) <= 1]
    return selected or [page.image_path for page in pages]


def _submission_review_image_paths(session: Session, submission_id: int, source_page: int | None) -> list[Path]:
    storage = get_storage_service()
    pages = session.execute(
        select(SubmissionPage)
        .where(SubmissionPage.submission_id == submission_id)
        .order_by(SubmissionPage.page_no.asc())
    ).scalars().all()
    if not pages:
        return []
    if source_page is None:
        selected_pages = pages
    else:
        selected_pages = [page for page in pages if abs(page.page_no - source_page) <= 1] or pages
    return [storage.path_for(page.image_path) for page in selected_pages]


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
    ocr_started_at = time.perf_counter()
    ocr_reference_text = build_ocr_reference_text(rendered_pages, "vision_rubric")
    if ocr_reference_text:
        logger.info(
            "Rubric OCR reference built exam_id=%s pages=%s chars=%s duration_seconds=%.2f",
            exam_id,
            len(rendered_pages),
            len(ocr_reference_text),
            time.perf_counter() - ocr_started_at,
        )
    prompt_variables = {
        "exam_title": exam.title,
        "teacher_notes": exam.description or "",
        "ocr_reference_text": format_ocr_reference_text(ocr_reference_text),
    }
    try:
        vision_started_at = time.perf_counter()
        completion = call_structured_json(
            model=settings.ai_vision_model,
            system_prompt_name="rubric_extraction.system.md",
            user_prompt_name="rubric_extraction.user.md",
            response_model=RubricParseResult,
            prompt_variables=prompt_variables,
            image_paths=[page.image_path for page in rendered_pages],
            request_profile="vision",
            route_key="vision_rubric",
        )
        logger.info(
            "Rubric vision completed exam_id=%s model=%s candidate_index=%s fallback=%s duration_seconds=%.2f",
            exam_id,
            completion.model,
            completion.candidate_index,
            completion.fallback_used,
            time.perf_counter() - vision_started_at,
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

    if submission.status != SubmissionStatus.rendering.value:
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
        ocr_reference_text=build_ocr_reference_text(rendered_pages, "vision_student_extraction"),
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

    if not grading_tasks:
        submission.total_score = Decimal("0")
        submission.status = SubmissionStatus.needs_review.value
        submission.error_message = "No gradable questions were found for this submission"
        session.commit()
        return _load_submission(session, submission.id)

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
                review_image_paths=_review_image_paths_from_rendered_pages(rendered_pages, sp),
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
    refresh_deduction_summary(session, submission.id)
    session.commit()
    return _load_submission(session, submission.id)


def apply_teacher_override(
    session: Session,
    answer_id: int,
    teacher_override_score: float | None = None,
    teacher_comment: str | None = None,
    reviewed: bool | None = None,
    update_teacher_override_score: bool = True,
    update_teacher_comment: bool = True,
) -> Answer:
    answer = session.get(Answer, answer_id)
    if answer is None:
        raise PipelineError(f"Answer {answer_id} not found")
    if update_teacher_override_score:
        answer.teacher_override_score = (
            _to_decimal(teacher_override_score) if teacher_override_score is not None else None
        )
    if update_teacher_comment:
        answer.teacher_comment = teacher_comment
    if reviewed is True:
        answer.needs_human_review = False
    elif reviewed is False:
        answer.needs_human_review = True
    session.flush()
    _recalculate_submission_total(session, answer.submission_id)
    refresh_deduction_summary(session, answer.submission_id)
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
    review_image_paths: list[Path] | None = None,
) -> tuple[Answer, list[AnswerRubricResult], bool]:
    if not answer_text.strip():
        started_at = time.perf_counter()
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
            True,
        )
        return answer, rubric_results, needs_review

    fast_attempt = _call_grading_model(
        question=question,
        answer_text=answer_text,
        extraction_confidence=extraction_confidence,
        route_key="grading",
    )
    if fast_attempt is None:
        return _build_error_fallback(
            submission_id=submission_id,
            question=question,
            answer_text=answer_text,
            source_page=source_page,
            extraction_confidence=extraction_confidence,
            raw_response="ERROR: Fast grading failed",
        )

    review_triggers = _review_triggers_for_attempt(fast_attempt, max_score=question.max_score, answer_text=answer_text)
    review_attempt: GradingAttempt | None = None
    review_decision = "not_required"
    final_attempt = fast_attempt

    if settings.ai_grading_review_enabled and review_triggers:
        review_attempt = _call_grading_review_with_images(
            question=question,
            answer_text=answer_text,
            extraction_confidence=extraction_confidence,
            image_paths=review_image_paths or [],
        )
        if review_attempt is None:
            review_attempt = _call_grading_model(
                question=question,
                answer_text=answer_text,
                extraction_confidence=extraction_confidence,
                route_key="grading_review",
            )
        if review_attempt is None:
            review_decision = "failed"
        else:
            final_attempt = review_attempt
            review_decision = "accepted_review"
            if _score_delta_exceeds_threshold(fast_attempt.score, review_attempt.score, question.max_score):
                review_triggers.append("score_delta")
    elif review_triggers:
        review_decision = "needs_teacher_review"

    needs_review = bool(
        final_attempt.needs_human_review
        or "score_delta" in review_triggers
        or review_decision in {"failed", "needs_teacher_review"}
    )
    answer = _build_answer_from_attempt(
        submission_id=submission_id,
        question=question,
        answer_text=answer_text,
        source_page=source_page,
        attempt=final_attempt,
        needs_review=needs_review,
    )
    answer.fast_score = fast_attempt.score
    answer.fast_confidence = fast_attempt.confidence.value
    answer.fast_ai_comment = fast_attempt.ai_comment
    answer.fast_missing_points = fast_attempt.missing_points
    answer.fast_raw_ai_response = fast_attempt.raw_response
    answer.review_triggers = _dedupe_strings(review_triggers)
    answer.review_decision = review_decision
    if review_attempt is not None:
        answer.review_score = review_attempt.score
        answer.review_confidence = review_attempt.confidence.value
        answer.review_ai_comment = review_attempt.ai_comment
        answer.review_missing_points = review_attempt.missing_points
        answer.review_raw_ai_response = review_attempt.raw_response
        answer.review_model = review_attempt.model
    elif review_decision == "failed":
        answer.needs_human_review = True

    return answer, final_attempt.rubric_results, answer.needs_human_review


def _call_grading_review_with_images(
    *,
    question: QuestionSnapshot,
    answer_text: str,
    extraction_confidence: ConfidenceLevel,
    image_paths: list[Path],
) -> GradingAttempt | None:
    if not image_paths:
        logger.info("Image-grounded grading review skipped question_id=%s reason=skipped_no_image", question.id)
        return None
    if not _has_vision_capable_review_candidate():
        logger.info("Image-grounded grading review skipped question_id=%s reason=skipped_no_vision_candidate", question.id)
        return None
    started_at = time.perf_counter()
    grading_model = settings.effective_grading_model_for_route("grading_review")
    try:
        strictness = settings.ai_grading_strictness
        strictness_instructions = _strictness_instructions(strictness)
        completion = call_structured_json(
            model=grading_model,
            system_prompt_name="grading.system.md",
            user_prompt_name="grading_review.user.md",
            response_model=GradingResult,
            prompt_variables={
                "grading_input_json": json.dumps(_build_grading_input(question, answer_text), ensure_ascii=False, indent=2),
                "strictness": strictness,
                "strictness_instructions": strictness_instructions,
            },
            image_paths=image_paths,
            request_profile="vision",
            route_key="vision_grading_review",
        )
        return _build_grading_attempt(
            question=question,
            answer_text=answer_text,
            extraction_confidence=extraction_confidence,
            grading_result=completion.data,
            raw_response=completion.raw_text,
            model=completion.model,
        )
    except Exception as exc:  # noqa: BLE001 - review can fall back to text-only grading review
        logger.exception("Image-grounded grading review failed for question %s: %s", question.id, exc)
        return None
    finally:
        logger.info(
            "Image-grounded grading review completed question_id=%s question_no=%s model=%s image_count=%s duration_seconds=%.2f",
            question.id,
            question.question_no,
            grading_model,
            len(image_paths),
            time.perf_counter() - started_at,
        )


def _has_vision_capable_review_candidate() -> bool:
    return any(candidate.supports_vision for candidate in settings.ai_model_candidates("vision_grading_review"))


def _call_grading_model(
    *,
    question: QuestionSnapshot,
    answer_text: str,
    extraction_confidence: ConfidenceLevel,
    route_key: AIRouteKey,
) -> GradingAttempt | None:
    started_at = time.perf_counter()
    grading_model = settings.effective_grading_model_for_route(route_key)
    try:
        strictness = settings.ai_grading_strictness
        strictness_instructions = _strictness_instructions(strictness)
        completion = call_structured_json(
            model=grading_model,
            system_prompt_name="grading.system.md",
            user_prompt_name="grading.user.md",
            response_model=GradingResult,
            prompt_variables={
                "grading_input_json": json.dumps(_build_grading_input(question, answer_text), ensure_ascii=False, indent=2),
                "strictness": strictness,
                "strictness_instructions": strictness_instructions,
            },
            request_profile="grading",
            route_key=route_key,
        )
        return _build_grading_attempt(
            question=question,
            answer_text=answer_text,
            extraction_confidence=extraction_confidence,
            grading_result=completion.data,
            raw_response=completion.raw_text,
            model=completion.model,
        )
    except Exception as exc:  # noqa: BLE001 - grading can fall back to manual review
        logger.exception("Question grading failed for question %s route=%s: %s", question.id, route_key, exc)
        return None
    finally:
        logger.info(
            "Question grading completed question_id=%s question_no=%s route=%s model=%s duration_seconds=%.2f",
            question.id,
            question.question_no,
            route_key,
            grading_model,
            time.perf_counter() - started_at,
        )


def _build_grading_attempt(
    *,
    question: QuestionSnapshot,
    answer_text: str,
    extraction_confidence: ConfidenceLevel,
    grading_result: GradingResult,
    raw_response: str,
    model: str,
) -> GradingAttempt:
    rubric_results: list[AnswerRubricResult] = []
    rubric_lookup = {rubric_item.id: rubric_item for rubric_item in question.rubric_items}
    awarded_total = Decimal("0")
    missing_points = list(grading_result.missing_points)
    rubric_item_ids_seen: set[int] = set()
    missing_rubric_evidence = False

    for evaluation in grading_result.rubric_evaluation:
        rubric_item_id = _coerce_int(evaluation.rubric_item_id)
        rubric_item = rubric_lookup.get(rubric_item_id)
        if rubric_item is None:
            continue
        evidence = evaluation.evidence_from_student_answer.strip()
        awarded_score = _to_decimal(clamp_score(float(evaluation.awarded_score), 0.0, float(rubric_item.max_score)))
        if awarded_score > 0 and not evidence:
            missing_rubric_evidence = True
            awarded_score = Decimal("0")
        awarded_total += awarded_score
        rubric_item_ids_seen.add(rubric_item.id)
        rubric_results.append(
            AnswerRubricResult(
                rubric_item_id=rubric_item.id,
                awarded_score=awarded_score,
                evidence=evidence,
                reason=evaluation.reason.strip(),
            )
        )

    for rubric_item in question.rubric_items:
        if rubric_item.id in rubric_item_ids_seen:
            continue
        missing_rubric_evidence = True
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

    final_score = _apply_strictness_score_policy(
        score=_to_decimal(clamp_score(float(awarded_total), 0.0, float(question.max_score))),
        question=question,
        answer_text=answer_text,
        rubric_results=rubric_results,
    )
    final_confidence = _combine_confidence(extraction_confidence, grading_result.confidence)
    needs_review = bool(grading_result.needs_human_review or final_confidence == ConfidenceLevel.low)
    if needs_review and grading_result.final_comment.strip() and grading_result.final_comment.strip() not in missing_points:
        missing_points.append(grading_result.final_comment.strip())

    return GradingAttempt(
        score=final_score,
        confidence=final_confidence,
        ai_comment=grading_result.final_comment.strip(),
        missing_points=_dedupe_strings(missing_points),
        raw_response=raw_response,
        rubric_results=rubric_results,
        needs_human_review=needs_review,
        model=model,
        model_requested_review=grading_result.needs_human_review,
        missing_rubric_evidence=missing_rubric_evidence,
    )


def _apply_strictness_score_policy(
    *,
    score: Decimal,
    question: QuestionSnapshot,
    answer_text: str,
    rubric_results: list[AnswerRubricResult],
) -> Decimal:
    if not answer_text.strip() or settings.ai_grading_strictness != "lenient":
        return score
    if score > 0 or not _has_positive_rubric_evidence(rubric_results):
        return score
    floor = _to_decimal(float(question.max_score) * 0.05)
    cap = _to_decimal(min(float(question.max_score) * 0.1, 0.25))
    return _to_decimal(clamp_score(float(max(score, min(floor, cap))), 0.0, float(question.max_score)))


def _has_positive_rubric_evidence(rubric_results: list[AnswerRubricResult]) -> bool:
    return any(result.evidence.strip() and result.reason.strip() for result in rubric_results)


def _review_triggers_for_attempt(attempt: GradingAttempt, *, max_score: Decimal | None = None, answer_text: str = "") -> list[str]:
    triggers: list[str] = []
    if attempt.confidence == ConfidenceLevel.low:
        triggers.append("low_confidence")
    if attempt.model_requested_review:
        triggers.append("model_requested_review")
    if attempt.missing_rubric_evidence:
        triggers.append("missing_rubric_evidence")
    if answer_text.strip() and max_score is not None and max_score > 0 and attempt.score <= _to_decimal(float(max_score) * 0.25):
        triggers.append("non_empty_low_score")
    return triggers


def _score_delta_exceeds_threshold(fast_score: Decimal, review_score: Decimal, max_score: Decimal) -> bool:
    if max_score <= 0:
        return False
    return abs(fast_score - review_score) > _to_decimal(float(max_score) * settings.ai_grading_review_score_delta_ratio)


def _build_answer_from_attempt(
    *,
    submission_id: int,
    question: QuestionSnapshot,
    answer_text: str,
    source_page: int | None,
    attempt: GradingAttempt,
    needs_review: bool,
) -> Answer:
    return Answer(
        submission_id=submission_id,
        question_id=question.id,
        source_page=source_page,
        extracted_answer=answer_text,
        score=attempt.score,
        max_score=_to_decimal(question.max_score),
        confidence=attempt.confidence.value,
        ai_comment=attempt.ai_comment,
        missing_points=attempt.missing_points,
        needs_human_review=needs_review,
        teacher_override_score=None,
        teacher_comment=None,
        raw_ai_response=attempt.raw_response,
    )


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
1. Assess ONLY against the provided rubric items — do not add extra requirements.
2. Award credit for semantic equivalence even when wording, symbols, order, or Chinese-English phrasing differ.
3. Give generous partial credit for relevant attempts, but do not award credit for unrelated, contradictory, or unsupported content.
4. Every positive awarded_score must cite concrete evidence from the student's answer.
5. If evidence is ambiguous because of OCR or handwriting, award cautious partial credit and set lower confidence or needs_human_review.
6. Missing points should list rubric concepts that are absent, contradicted, or unsupported by visible evidence.
7. The final_comment should be encouraging while clearly noting remaining gaps.""",
        "moderate": """Grade fairly. Rules:
1. Assess only against the provided rubric items and do not add extra requirements.
2. Award partial credit proportional to the relevant evidence the student actually provided.
3. Answers that are unrelated, purely generic, or contradicted by the rubric may receive 0 for that rubric item.
4. Every positive awarded_score must cite concrete evidence from the student's answer.
5. Mark missing_points for concepts that are missing, substantially incorrect, or not supported by evidence.""",
        "strict": """Grade strictly. Rules:
1. Award credit only when the student's answer explicitly and accurately satisfies the rubric item.
2. Require complete reasoning, key terms, formula structure, units, and calculations when the rubric expects them.
3. Unrelated, incorrect, unsupported, or purely generic answers should receive 0 for that rubric item.
4. Every positive awarded_score must cite concrete evidence from the student's answer.
5. Mark missing_points for any missing, incorrect, or unsupported part of the rubric item.""",
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


def review_answer_with_strong_model(
    session: Session,
    answer_id: int,
    trigger: str = "score_variance",
) -> Answer:
    answer = session.execute(
        select(Answer)
        .where(Answer.id == answer_id)
        .options(selectinload(Answer.question).selectinload(Question.rubric_items), selectinload(Answer.rubric_results))
    ).scalar_one_or_none()
    if answer is None:
        raise PipelineError(f"Answer {answer_id} not found")
    question = _snapshot_question(answer.question)
    triggers = _dedupe_strings([*(answer.review_triggers or []), trigger])
    if answer.review_score is not None:
        answer.review_triggers = triggers
        session.commit()
        return answer
    claimed = session.execute(
        sa_update(Answer)
        .where(Answer.id == answer_id, Answer.review_score.is_(None))
        .values(review_decision="in_progress")
    ).rowcount
    if not claimed:
        session.refresh(answer)
        return answer
    review_attempt = _call_grading_review_with_images(
        question=question,
        answer_text=answer.extracted_answer,
        extraction_confidence=ConfidenceLevel(answer.confidence),
        image_paths=_submission_review_image_paths(session, answer.submission_id, answer.source_page),
    )
    if review_attempt is None:
        review_attempt = _call_grading_model(
            question=question,
            answer_text=answer.extracted_answer,
            extraction_confidence=ConfidenceLevel(answer.confidence),
            route_key="grading_review",
        )
    answer.review_triggers = triggers
    if review_attempt is None:
        answer.review_decision = "failed"
        answer.needs_human_review = True
        session.commit()
        return answer

    fast_score = answer.fast_score if answer.fast_score is not None else answer.score
    answer.review_score = review_attempt.score
    answer.review_confidence = review_attempt.confidence.value
    answer.review_ai_comment = review_attempt.ai_comment
    answer.review_missing_points = review_attempt.missing_points
    answer.review_raw_ai_response = review_attempt.raw_response
    answer.review_model = review_attempt.model
    answer.review_decision = "accepted_review"
    answer.score = review_attempt.score
    answer.confidence = review_attempt.confidence.value
    answer.ai_comment = review_attempt.ai_comment
    answer.missing_points = review_attempt.missing_points
    answer.raw_ai_response = review_attempt.raw_response
    if _score_delta_exceeds_threshold(fast_score, review_attempt.score, question.max_score):
        answer.review_triggers = _dedupe_strings([*triggers, "score_delta"])
        answer.needs_human_review = True
    else:
        answer.needs_human_review = review_attempt.needs_human_review
    for rubric_result in review_attempt.rubric_results:
        rubric_result.answer_id = answer.id
    session.execute(delete(AnswerRubricResult).where(AnswerRubricResult.answer_id == answer.id))
    session.flush()
    for rubric_result in review_attempt.rubric_results:
        session.add(rubric_result)
    _recalculate_submission_total(session, answer.submission_id)
    refresh_deduction_summary(session, answer.submission_id)
    session.commit()
    return answer


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
    ocr_reference_text: str = "",
) -> tuple[StudentExtractionResult, str]:
    try:
        vision_started_at = time.perf_counter()
        completion = call_structured_json(
            model=settings.ai_vision_model,
            system_prompt_name="student_extraction.system.md",
            user_prompt_name="student_extraction.user.md",
            response_model=StudentExtractionResult,
            prompt_variables={
                "exam_title": exam_title,
                "questions_json": questions_json,
                "ocr_reference_text": format_ocr_reference_text(ocr_reference_text),
            },
            image_paths=image_paths,
            request_profile="vision",
            route_key="vision_student_extraction",
        )
        logger.info(
            "Student extraction vision completed model=%s candidate_index=%s fallback=%s pages=%s duration_seconds=%.2f",
            completion.model,
            completion.candidate_index,
            completion.fallback_used,
            len(image_paths),
            time.perf_counter() - vision_started_at,
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
        any_review = any_review or answer.needs_human_review
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


def generate_deduction_summary(submission: Submission) -> str:
    """Render a human-readable Markdown-ish summary of where the student lost points.

    The returned text follows the rubric structure 1:1 so teachers can audit it
    quickly. Each question with a non-zero deduction becomes its own bullet block.
    """

    questions_by_id = {question.id: question for question in submission.exam.questions}
    answers_in_order = sorted(
        submission.answers,
        key=lambda answer: (
            questions_by_id.get(answer.question_id).order_index
            if questions_by_id.get(answer.question_id) is not None
            else answer.id
        ),
    )
    blocks: list[str] = []
    for answer in answers_in_order:
        question = questions_by_id.get(answer.question_id) or answer.question
        question_max = _to_decimal(answer.max_score if answer.max_score else (question.max_score if question else Decimal("0")))
        if question_max <= 0:
            continue
        effective = _to_decimal(
            answer.teacher_override_score if answer.teacher_override_score is not None else answer.score
        )
        if effective >= question_max:
            continue
        deduction = _to_decimal(question_max - effective)
        question_label = f"第 {question.question_no} 题" if question else f"题目 {answer.question_id}"
        title_suffix = f"：{question.title.strip()}" if question and question.title else ""
        header = (
            f"- {question_label}{title_suffix}（满分 {_format_score_value(question_max)}，"
            f"得 {_format_score_value(effective)}，扣 {_format_score_value(deduction)}）"
        )
        bullet_lines: list[str] = []
        rubric_items_by_id = {item.id: item for item in (question.rubric_items if question else [])}
        for rubric_result in answer.rubric_results:
            rubric_item = rubric_items_by_id.get(rubric_result.rubric_item_id)
            rubric_max = _to_decimal(rubric_item.max_score) if rubric_item else _to_decimal(0)
            awarded = _to_decimal(rubric_result.awarded_score)
            if rubric_max <= 0 or awarded >= rubric_max:
                continue
            lost = _to_decimal(rubric_max - awarded)
            description = (rubric_item.description.strip() if rubric_item else f"评分项 #{rubric_result.rubric_item_id}")
            reason = (rubric_result.reason or "").strip() or "未给出说明，请人工复核"
            bullet_lines.append(
                f"  • {description}：扣 {_format_score_value(lost)} 分 —— {reason}"
            )
        if not bullet_lines:
            fallback_reason = (answer.ai_comment or "").strip() or "AI 未输出具体扣分依据，请人工复核"
            bullet_lines.append(f"  • {fallback_reason}")
        blocks.append("\n".join([header, *bullet_lines]))
    if not blocks:
        return "本卷没有扣分项，全部题目得满分。"
    return "\n".join(blocks)


def refresh_deduction_summary(session: Session, submission_id: int) -> Submission | None:
    """Regenerate `Submission.deduction_summary` from current rubric_results.

    Skips if the teacher has already edited the summary (`deduction_summary_edited`).
    """

    submission = _load_submission(session, submission_id)
    if submission.deduction_summary_edited:
        return submission
    submission.deduction_summary = generate_deduction_summary(submission)
    session.flush()
    return submission


def set_teacher_deduction_summary(
    session: Session,
    submission_id: int,
    summary: str | None,
    *,
    reset: bool = False,
) -> Submission:
    submission = _load_submission(session, submission_id)
    if reset:
        submission.deduction_summary_edited = False
        submission.deduction_summary = generate_deduction_summary(submission)
    else:
        normalized = (summary or "").strip()
        submission.deduction_summary = normalized or None
        submission.deduction_summary_edited = bool(normalized)
    session.commit()
    return submission


def _format_score_value(value: Decimal) -> str:
    quantized = _to_decimal(value)
    if quantized == quantized.to_integral_value():
        return str(quantized.to_integral_value())
    return str(quantized.normalize())

