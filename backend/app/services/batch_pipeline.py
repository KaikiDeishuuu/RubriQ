from __future__ import annotations

import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, func, select, update as sa_update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import (
    Answer,
    BatchPage,
    BatchSplitCandidate,
    BatchStatus,
    BatchUploadMode,
    Exam,
    Question,
    Submission,
    SubmissionBatch,
    SubmissionStatus,
)
from app.schemas.ai import PageHeaderExtraction
from app.schemas.batch import BatchCandidateUpdate
from app.services.llm import call_structured_json
from app.services.ocr import HeaderOCRDiagnostic, extract_header_text_diagnostic, format_ocr_reference_text
from app.services.pipeline import _to_decimal, review_answer_with_strong_model
from app.services.pdf import crop_top_region, get_pdf_page_count, hash_file, render_pdf_to_images, split_pdf_pages
from app.services.roster import (
    RosterIndex,
    RosterMatch,
    build_roster_index,
    match_roster_identity,
)
from app.storage.local import get_storage_service
from app.utils.errors import sanitized_error_summary
from app.utils.files import PDF_SIGNATURE, sanitize_filename

logger = logging.getLogger(__name__)

SPLIT_CONFIDENCE_THRESHOLD = 0.75
MAX_REASONABLE_SPLIT_PAGE_NUMBER = 200
_STUDENT_NAME_NOISE_TOKENS = {"姓名", "学生", "学号", "学籍号", "考号", "页码", "第", "页面"}
_STUDENT_ID_NOISE_TOKENS = {
    "answer",
    "batch",
    "exam",
    "grade",
    "grading",
    "page",
    "paper",
    "question",
    "quiz",
    "score",
    "student",
    "submission",
    "test",
}
ACTIVE_SUBMISSION_STATUSES = {
    SubmissionStatus.processing.value,
    SubmissionStatus.rendering.value,
    SubmissionStatus.extracting.value,
    SubmissionStatus.grading.value,
}
STARTABLE_SUBMISSION_STATUSES = {
    SubmissionStatus.uploaded.value,
    SubmissionStatus.failed.value,
}
COMPLETED_SUBMISSION_STATUSES = {
    SubmissionStatus.graded.value,
    SubmissionStatus.needs_review.value,
}


class BatchPipelineError(RuntimeError):
    pass


@dataclass(slots=True)
class BatchConfirmResult:
    batch: SubmissionBatch
    created_submission_count: int
    failed_candidate_count: int


@dataclass(slots=True)
class ParsedStudentIdentity:
    student_id: str | None
    student_name: str | None
    confidence: float


@dataclass(slots=True)
class RenderedHeaderCrop:
    page_no: int
    page_image_path: Path
    crop_path: Path
    extracted_text: str


@dataclass(slots=True)
class HeaderExtractionResult:
    page_no: int
    page_image_path: Path
    crop_path: Path
    extracted_text: str
    header_data: dict[str, Any]
    raw_text: str
    error_message: str | None


def load_batch_detail(session: Session, batch_id: int) -> SubmissionBatch:
    stmt = (
        select(SubmissionBatch)
        .where(SubmissionBatch.id == batch_id)
        .options(
            selectinload(SubmissionBatch.pages),
            selectinload(SubmissionBatch.candidates).selectinload(BatchSplitCandidate.submission),
            selectinload(SubmissionBatch.submissions),
        )
    )
    batch = session.execute(stmt).scalar_one_or_none()
    if batch is None:
        raise BatchPipelineError(f"Batch {batch_id} not found")
    return batch


def list_exam_batches(session: Session, exam_id: int) -> list[SubmissionBatch]:
    stmt = (
        select(SubmissionBatch)
        .where(SubmissionBatch.exam_id == exam_id)
        .options(
            selectinload(SubmissionBatch.pages),
            selectinload(SubmissionBatch.candidates).selectinload(BatchSplitCandidate.submission),
            selectinload(SubmissionBatch.submissions),
        )
        .order_by(SubmissionBatch.created_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


def prepare_batch_split(session: Session, batch_id: int) -> SubmissionBatch:
    batch = load_batch_detail(session, batch_id)
    batch.status = BatchStatus.splitting.value
    batch.error_message = None
    session.commit()
    try:
        if batch.mode == BatchUploadMode.zip.value:
            _prepare_zip_batch(session, batch)
        elif batch.mode == BatchUploadMode.combined_fixed.value:
            _prepare_fixed_page_batch(session, batch)
        elif batch.mode == BatchUploadMode.combined_auto.value:
            _prepare_auto_split_batch(session, batch)
        else:
            raise BatchPipelineError(f"Unsupported batch mode {batch.mode}")
    except Exception as exc:
        logger.exception("Batch split preparation failed batch_id=%s", batch.id)
        batch.status = BatchStatus.failed.value
        batch.error_message = sanitized_error_summary(exc, "Batch split preparation failed")
        session.commit()
        raise
    return load_batch_detail(session, batch.id)


def update_batch_candidates(
    session: Session,
    batch_id: int,
    updates: list[BatchCandidateUpdate],
) -> SubmissionBatch:
    batch = load_batch_detail(session, batch_id)
    if batch.status in {BatchStatus.grading.value, BatchStatus.completed.value}:
        raise BatchPipelineError("Cannot edit split candidates after grading has started")
    active_updates = [update for update in updates if not update.excluded]
    if active_updates:
        _validate_candidate_ranges(active_updates, batch.total_pages)
    roster_index = build_roster_index(session, batch.exam_id)
    seen_roster_entry_ids: set[int] = set()
    for update in active_updates:
        if update.roster_entry_id is None:
            continue
        if update.roster_entry_id in seen_roster_entry_ids:
            raise BatchPipelineError("同一名单条目不能绑定到多个候选段")
        seen_roster_entry_ids.add(update.roster_entry_id)
        if update.roster_entry_id not in {entry.id for entry in roster_index.entries}:
            raise BatchPipelineError("名单条目无效或不属于本考试")
    existing = {candidate.id: candidate for candidate in batch.candidates}
    for fallback_index, update in enumerate(updates, start=1):
        if update.id is not None and update.id in existing:
            candidate = existing[update.id]
        else:
            candidate = BatchSplitCandidate(batch_id=batch.id, candidate_index=update.candidate_index or fallback_index)
            session.add(candidate)
        candidate.candidate_index = update.candidate_index or fallback_index
        candidate.start_page = update.start_page
        candidate.end_page = update.end_page
        candidate.student_name = _clean_optional(update.student_name)
        candidate.student_id = _clean_optional(update.student_id)
        candidate.review_notes = _clean_optional(update.review_notes)
        candidate.excluded = update.excluded
        if update.roster_entry_id is not None:
            roster_entry = next(
                (entry for entry in roster_index.entries if entry.id == update.roster_entry_id),
                None,
            )
            candidate.roster_entry_id = update.roster_entry_id
            if roster_entry is not None:
                if roster_entry.student_name:
                    candidate.student_name = roster_entry.student_name
                if roster_entry.student_id:
                    candidate.student_id = roster_entry.student_id
        else:
            candidate.roster_entry_id = None
        candidate.confirmed = update.confirmed and not update.excluded
        candidate.needs_review = not candidate.confirmed or not candidate.student_name or not candidate.student_id
        if candidate.excluded:
            candidate.needs_review = True
        elif candidate.confirmed and candidate.split_confidence < SPLIT_CONFIDENCE_THRESHOLD:
            candidate.needs_review = False
    batch.split_version += 1
    batch.status = _split_status_for_candidates(list(batch.candidates))
    session.commit()
    return load_batch_detail(session, batch.id)


def confirm_batch_split(session: Session, batch_id: int) -> BatchConfirmResult:
    batch = load_batch_detail(session, batch_id)
    active_candidates = _active_candidates(list(batch.candidates))
    if not active_candidates:
        raise BatchPipelineError("At least one non-ignored split candidate is required")
    unconfirmed = [candidate for candidate in active_candidates if not candidate.confirmed]
    if unconfirmed:
        raise BatchPipelineError("All non-ignored split candidates must be confirmed before grading")
    invalid = [candidate for candidate in active_candidates if not candidate.student_name or not candidate.student_id]
    if invalid:
        raise BatchPipelineError("All confirmed split candidates must have student name and ID")
    seen_roster_ids: set[int] = set()
    for candidate in active_candidates:
        if candidate.roster_entry_id is None:
            continue
        if candidate.roster_entry_id in seen_roster_ids:
            raise BatchPipelineError("同一名单条目不能绑定到多个候选段，请检查后再确认")
        seen_roster_ids.add(candidate.roster_entry_id)

    batch.status = BatchStatus.materializing.value
    session.commit()

    created_count = 0
    failed_count = 0
    if batch.mode == BatchUploadMode.zip.value:
        for candidate in active_candidates:
            try:
                submission = candidate.submission
                if submission is None:
                    submission = _create_submission_from_candidate(session, batch, candidate, candidate.source_storage_path)
                    candidate.submission = submission
                submission.student_name = candidate.student_name
                submission.student_id = candidate.student_id
                submission.status = SubmissionStatus.uploaded.value
                submission.split_confirmed = True
                submission.split_confidence = candidate.split_confidence
                candidate.needs_review = False
                candidate.error_message = None
                created_count += 1
            except Exception as exc:
                candidate.error_message = sanitized_error_summary(exc, "Candidate materialization failed")
                failed_count += 1
            session.flush()
    else:
        storage = get_storage_service()
        source_path = storage.path_for(batch.source_storage_path)
        output_dir = storage.path_for(f"exams/{batch.exam_id}/batches/{batch.id}/submissions")
        page_ranges = [(candidate.start_page, candidate.end_page) for candidate in active_candidates]
        try:
            split_paths = split_pdf_pages(source_path, page_ranges, output_dir)
        except Exception as exc:
            batch.status = BatchStatus.failed.value
            batch.error_message = sanitized_error_summary(exc, "Batch processing failed")
            session.commit()
            raise BatchPipelineError(f"Failed to split combined PDF: {exc}") from exc
        for candidate, split_path in zip(active_candidates, split_paths, strict=True):
            try:
                relative_path = storage.relative_path_for(split_path)
                candidate.source_storage_path = relative_path
                submission = candidate.submission or _create_submission_from_candidate(session, batch, candidate, relative_path)
                candidate.submission = submission
                submission.student_name = candidate.student_name
                submission.student_id = candidate.student_id
                submission.original_pdf_path = relative_path
                submission.status = SubmissionStatus.uploaded.value
                submission.split_confirmed = True
                submission.split_confidence = candidate.split_confidence
                candidate.needs_review = False
                candidate.error_message = None
                created_count += 1
            except Exception as exc:
                candidate.error_message = sanitized_error_summary(exc, "Candidate materialization failed")
                failed_count += 1
            session.flush()

    batch.status = BatchStatus.ready_for_grading.value if failed_count == 0 else BatchStatus.completed_with_errors.value
    session.commit()
    return BatchConfirmResult(
        batch=load_batch_detail(session, batch.id),
        created_submission_count=created_count,
        failed_candidate_count=failed_count,
    )


def start_batch_grading(session: Session, batch_id: int) -> tuple[SubmissionBatch, int]:
    batch = load_batch_detail(session, batch_id)
    if batch.status not in {BatchStatus.ready_for_grading.value, BatchStatus.completed_with_errors.value}:
        raise BatchPipelineError("Batch split must be confirmed before grading")
    _ensure_exam_has_gradable_questions(session, batch.exam_id)
    _ensure_exam_roster_confirmed(session, batch.exam_id)
    queued_count = _dispatch_next_batch_chunk(session, batch, eligible_statuses=STARTABLE_SUBMISSION_STATUSES)
    if queued_count > 0:
        batch.status = BatchStatus.grading.value
        session.commit()
    else:
        refresh_batch_grading_status(session, batch.id)
    return load_batch_detail(session, batch.id), queued_count


def _dispatch_next_batch_chunk(
    session: Session,
    batch: SubmissionBatch,
    *,
    eligible_statuses: set[str] | None = None,
) -> int:
    """Queue up to settings.ai_grading_batch_size pending submissions for this batch.

    Returns the number of submissions newly queued. Older chunks must finish before
    a new chunk starts; callers should invoke this when the previous chunk is done.

    `eligible_statuses` defaults to {uploaded} for the auto-redispatch loop so that
    failed submissions are not retried indefinitely. Pass STARTABLE_SUBMISSION_STATUSES
    explicitly for user-triggered start to retry previously failed ones once.
    """

    from app.workers.tasks import process_submission_task

    statuses = eligible_statuses if eligible_statuses is not None else {SubmissionStatus.uploaded.value}
    pending = [
        submission
        for submission in batch.submissions
        if submission.split_confirmed and submission.status in statuses
    ]
    if not pending:
        return 0
    chunk_size = max(1, settings.ai_grading_batch_size)
    chunk = sorted(pending, key=lambda submission: submission.id)[:chunk_size]
    queued_submission_ids: list[int] = []
    for submission in chunk:
        claimed = session.execute(
            sa_update(Submission)
            .where(Submission.id == submission.id, Submission.status.in_(statuses))
            .values(status=SubmissionStatus.processing.value, error_message=None)
        ).rowcount
        if claimed:
            queued_submission_ids.append(submission.id)
    if queued_submission_ids:
        session.commit()
        for submission_id in queued_submission_ids:
            process_submission_task.delay(submission_id)
    return len(queued_submission_ids)


def _ensure_exam_roster_confirmed(session: Session, exam_id: int) -> None:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise BatchPipelineError(f"Exam {exam_id} not found")
    if exam.roster_status != "confirmed":
        raise BatchPipelineError(
            "考试名单尚未确认，请先在「考试名单」步骤上传并确认名单后再开始批改。"
        )


def _ensure_exam_has_gradable_questions(session: Session, exam_id: int) -> None:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise BatchPipelineError(f"Exam {exam_id} not found")
    question_count = session.execute(select(func.count(Question.id)).where(Question.exam_id == exam_id)).scalar_one()
    if question_count == 0:
        raise BatchPipelineError("No gradable questions were found. Please parse the rubric before starting grading.")



def refresh_batch_grading_status(session: Session, batch_id: int) -> SubmissionBatch:
    batch = load_batch_detail(session, batch_id)
    submissions = [submission for submission in batch.submissions if submission.split_confirmed]
    if not submissions:
        return batch
    if any(submission.status in ACTIVE_SUBMISSION_STATUSES for submission in submissions):
        next_status = BatchStatus.grading.value
    else:
        # Current chunk finished. If more pending submissions exist, dispatch the next chunk
        # to keep grading drift bounded per chunk and reduce AI hallucination risk.
        # Auto-loop only retries `uploaded` submissions; failed ones are left for explicit retry.
        pending_remaining = any(
            submission.status == SubmissionStatus.uploaded.value for submission in submissions
        )
        if batch.status == BatchStatus.grading.value and pending_remaining:
            queued = _dispatch_next_batch_chunk(session, batch)
            if queued > 0:
                # Stay in grading state; new tasks will trigger another refresh on completion.
                return load_batch_detail(session, batch.id)
        if any(submission.status == SubmissionStatus.failed.value for submission in submissions):
            next_status = BatchStatus.completed_with_errors.value
        elif all(submission.status in COMPLETED_SUBMISSION_STATUSES for submission in submissions):
            if _queue_batch_review_if_needed(session, batch):
                next_status = BatchStatus.grading.value
            elif batch.ai_review_status == "failed":
                next_status = BatchStatus.completed_with_errors.value
            elif batch.ai_review_status == "queued" or batch.ai_review_status == "running":
                next_status = BatchStatus.grading.value
            else:
                next_status = BatchStatus.completed.value
        else:
            next_status = batch.status
    if batch.status != next_status:
        batch.status = next_status
        session.commit()
    return load_batch_detail(session, batch.id)


def review_batch_grading(session: Session, batch_id: int) -> SubmissionBatch:
    batch = load_batch_detail(session, batch_id)
    if batch.ai_review_status == "completed" or not settings.ai_grading_review_enabled:
        return batch
    batch.ai_review_status = "running"
    batch.ai_review_error_message = None
    batch.status = BatchStatus.grading.value
    session.commit()
    try:
        answer_ids = _batch_variance_review_answer_ids(session, batch.id)
        for answer_id in answer_ids:
            review_answer_with_strong_model(session, answer_id, trigger="score_variance")
        batch = load_batch_detail(session, batch.id)
        batch.ai_review_status = "completed"
        batch.ai_review_error_message = None
        batch.status = _terminal_batch_status(batch)
        session.commit()
    except Exception as exc:
        logger.exception("Batch grading review failed batch_id=%s", batch_id)
        batch = load_batch_detail(session, batch_id)
        batch.ai_review_status = "failed"
        batch.ai_review_error_message = sanitized_error_summary(exc, "Batch grading review failed")
        batch.status = BatchStatus.completed_with_errors.value
        session.commit()
        raise
    return load_batch_detail(session, batch_id)


def _queue_batch_review_if_needed(session: Session, batch: SubmissionBatch) -> bool:
    if not settings.ai_grading_review_enabled or batch.ai_review_status in {"queued", "running", "completed", "failed"}:
        return False
    if not _batch_variance_review_answer_ids(session, batch.id):
        batch.ai_review_status = "completed"
        session.commit()
        return False
    from app.workers.tasks import review_batch_grading_task

    claimed = session.execute(
        sa_update(SubmissionBatch)
        .where(SubmissionBatch.id == batch.id, SubmissionBatch.ai_review_status == "not_started")
        .values(ai_review_status="queued", ai_review_error_message=None)
    ).rowcount
    session.commit()
    if claimed:
        review_batch_grading_task.delay(batch.id)
    return bool(claimed)


def _batch_variance_review_answer_ids(session: Session, batch_id: int) -> list[int]:
    stmt = (
        select(Answer)
        .join(Submission, Answer.submission_id == Submission.id)
        .where(Submission.batch_id == batch_id, Submission.split_confirmed.is_(True))
    )
    answers = list(session.execute(stmt).scalars().all())
    by_question: dict[int, list[Answer]] = {}
    for answer in answers:
        by_question.setdefault(answer.question_id, []).append(answer)
    review_answer_ids: list[int] = []
    for question_answers in by_question.values():
        if len(question_answers) < settings.ai_grading_review_variance_min_answers:
            continue
        max_score = max((answer.max_score for answer in question_answers), default=0)
        if max_score <= 0:
            continue
        reviewable_answers = [
            answer
            for answer in question_answers
            if answer.review_score is None
            and answer.teacher_override_score is None
            and answer.review_decision != "teacher_reviewed"
        ]
        scores = [answer.fast_score if answer.fast_score is not None else answer.score for answer in question_answers]
        score_range = max(scores) - min(scores)
        if score_range <= _to_decimal(float(max_score) * settings.ai_grading_review_variance_range_ratio):
            continue
        review_answer_ids.extend(answer.id for answer in reviewable_answers)
    return review_answer_ids


def _terminal_batch_status(batch: SubmissionBatch) -> str:
    submissions = [submission for submission in batch.submissions if submission.split_confirmed]
    if any(submission.status == SubmissionStatus.failed.value for submission in submissions):
        return BatchStatus.completed_with_errors.value
    return BatchStatus.completed.value


def _prepare_zip_batch(session: Session, batch: SubmissionBatch) -> None:
    storage = get_storage_service()
    zip_path = storage.path_for(batch.source_storage_path)
    _clear_batch_children(session, batch.id, clear_submissions=True)
    roster_index = build_roster_index(session, batch.exam_id)
    candidate_count = 0
    failed_count = 0
    pdf_entry_count = 0
    cumulative_uncompressed_bytes = 0
    per_entry_max_bytes = settings.max_upload_bytes
    total_max_bytes = settings.batch_zip_max_uncompressed_bytes
    max_entries = settings.batch_zip_max_entries
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            pdf_entry_count += 1
            if pdf_entry_count > max_entries:
                raise BatchPipelineError(
                    f"ZIP archive contains more than {max_entries} PDF entries"
                )
            if _zip_entry_escapes(info.filename):
                candidate_count += 1
                _add_failed_candidate(session, batch, candidate_count, info.filename, "ZIP entry path is not allowed")
                failed_count += 1
                continue
            if info.file_size > per_entry_max_bytes:
                candidate_count += 1
                _add_failed_candidate(
                    session,
                    batch,
                    candidate_count,
                    PurePosixPath(info.filename).name,
                    f"ZIP entry exceeds the {per_entry_max_bytes // (1024 * 1024)} MiB per-file limit",
                )
                failed_count += 1
                continue
            cumulative_uncompressed_bytes += info.file_size
            if cumulative_uncompressed_bytes > total_max_bytes:
                raise BatchPipelineError(
                    "ZIP archive uncompressed size exceeds the configured limit"
                )
            candidate_count += 1
            original_name = PurePosixPath(info.filename).name
            try:
                data = archive.read(info)
                if not data.startswith(PDF_SIGNATURE):
                    raise BatchPipelineError("ZIP entry is not a valid PDF")
                stored = storage.save_bytes(
                    storage.unique_pdf_path(f"exams/{batch.exam_id}/submissions", original_name),
                    data,
                )
                identity = parse_student_identity_from_filename(original_name)
                roster_match = match_roster_identity(roster_index, identity.student_name, identity.student_id)
                student_name = identity.student_name
                student_id = identity.student_id
                confidence = identity.confidence
                roster_entry_id: int | None = None
                review_notes: str | None = None
                if roster_match.entry is not None:
                    student_name = roster_match.entry.student_name or student_name
                    student_id = roster_match.entry.student_id or student_id
                    confidence = max(confidence, 0.95)
                    roster_entry_id = roster_match.entry.id
                elif not roster_index.is_empty():
                    review_notes = "未在名单中找到匹配学生"
                needs_review = (
                    confidence < 1.0
                    or not student_id
                    or not student_name
                    or (review_notes is not None)
                )
                if review_notes is None and needs_review:
                    review_notes = "文件名无法可靠解析学生信息"
                first_preview_page = _next_batch_page_no(session, batch.id)
                pdf_page_count = get_pdf_page_count(stored.absolute_path)
                candidate = BatchSplitCandidate(
                    batch_id=batch.id,
                    candidate_index=candidate_count,
                    start_page=first_preview_page,
                    end_page=first_preview_page + pdf_page_count - 1,
                    student_name=student_name,
                    student_id=student_id,
                    split_confidence=confidence,
                    needs_review=needs_review,
                    confirmed=False,
                    source_filename=original_name,
                    source_storage_path=stored.relative_path,
                    review_notes=review_notes,
                    roster_entry_id=roster_entry_id,
                )
                session.add(candidate)
                session.flush()
                submission = _create_submission_from_candidate(session, batch, candidate, stored.relative_path)
                submission.status = SubmissionStatus.needs_review.value if needs_review else SubmissionStatus.uploaded.value
                candidate.submission = submission
                _record_zip_pages(session, batch, stored.relative_path, candidate_count)
            except Exception as exc:
                _add_failed_candidate(session, batch, candidate_count, original_name, str(exc))
                failed_count += 1
            session.flush()
    batch.total_pages = len(batch.pages)
    if candidate_count == 0:
        raise BatchPipelineError("ZIP file does not contain any PDF files")
    batch.status = _split_status_for_candidates(list(batch.candidates)) if failed_count == 0 else BatchStatus.needs_split_review.value
    session.commit()


def _prepare_fixed_page_batch(session: Session, batch: SubmissionBatch) -> None:
    if not batch.pages_per_submission or batch.pages_per_submission < 1:
        raise BatchPipelineError("pages_per_submission is required for fixed-page batches")
    storage = get_storage_service()
    source_path = storage.path_for(batch.source_storage_path)
    _clear_batch_children(session, batch.id, clear_submissions=False)
    rendered_pages = render_pdf_to_images(
        source_path,
        storage.path_for(f"rendered/batches/{batch.id}/pages"),
        dpi=settings.render_dpi,
    )
    for rendered_page in rendered_pages:
        session.add(
            BatchPage(
                batch_id=batch.id,
                page_no=rendered_page.page_no,
                image_path=storage.relative_path_for(rendered_page.image_path),
                page_hash=hash_file(rendered_page.image_path),
                extracted_text=rendered_page.extracted_text,
            )
        )
    batch.total_pages = len(rendered_pages)

    roster_index = build_roster_index(session, batch.exam_id)
    expected_candidate_count = -(-len(rendered_pages) // batch.pages_per_submission)  # ceil
    roster_size = len(roster_index.entries)
    roster_count_mismatch = (
        not roster_index.is_empty() and roster_size != expected_candidate_count
    )
    candidate_index = 0
    for start_page in range(1, len(rendered_pages) + 1, batch.pages_per_submission):
        candidate_index += 1
        end_page = min(start_page + batch.pages_per_submission - 1, len(rendered_pages))
        incomplete = (end_page - start_page + 1) != batch.pages_per_submission
        roster_entry = roster_index.order_to_entry.get(candidate_index - 1)
        student_name = roster_entry.student_name if roster_entry else None
        student_id = roster_entry.student_id if roster_entry else None
        roster_entry_id = roster_entry.id if roster_entry else None
        if roster_entry is not None:
            split_confidence = 0.65 if incomplete else 0.95
        else:
            split_confidence = 0.65 if incomplete else 0.9
        review_notes_parts: list[str] = []
        if incomplete:
            review_notes_parts.append("总页数不能被每份页数整除，需要确认最后一段")
        if roster_count_mismatch:
            review_notes_parts.append(
                f"名单条目数 {roster_size} 与机械拆分份数 {expected_candidate_count} 不一致，请确认绑定"
            )
        elif roster_entry is None and not roster_index.is_empty():
            review_notes_parts.append("未从名单中找到对应学生")
        needs_review = bool(
            incomplete
            or roster_count_mismatch
            or roster_entry is None
            or not student_name
            or not student_id
        )
        session.add(
            BatchSplitCandidate(
                batch_id=batch.id,
                candidate_index=candidate_index,
                start_page=start_page,
                end_page=end_page,
                student_name=student_name,
                student_id=student_id,
                split_confidence=split_confidence,
                needs_review=needs_review,
                confirmed=False,
                review_notes=" / ".join(review_notes_parts) or None,
                roster_entry_id=roster_entry_id,
            )
        )
    batch.status = _split_status_for_candidates(list(batch.candidates))
    session.commit()


def _prepare_auto_split_batch(session: Session, batch: SubmissionBatch) -> None:
    storage = get_storage_service()
    source_path = storage.path_for(batch.source_storage_path)
    _clear_batch_children(session, batch.id, clear_submissions=False)
    rendered_pages = render_pdf_to_images(
        source_path,
        storage.path_for(f"rendered/batches/{batch.id}/pages"),
        dpi=settings.render_dpi,
    )
    header_crops = [
        RenderedHeaderCrop(
            page_no=rendered_page.page_no,
            page_image_path=rendered_page.image_path,
            crop_path=crop_top_region(
                rendered_page.image_path,
                storage.path_for(f"rendered/batches/{batch.id}/headers/page-{rendered_page.page_no:03d}.png"),
            ),
            extracted_text=rendered_page.extracted_text,
        )
        for rendered_page in rendered_pages
    ]
    header_extractions = _extract_headers_for_auto_split(header_crops)
    header_results: list[dict[str, Any]] = []
    for extraction in header_extractions:
        header_results.append(extraction.header_data)
        session.add(
            BatchPage(
                batch_id=batch.id,
                page_no=extraction.page_no,
                image_path=storage.relative_path_for(extraction.page_image_path),
                page_hash=hash_file(extraction.page_image_path),
                extracted_text=extraction.extracted_text,
                header_extraction_json=extraction.header_data,
                raw_ai_response=extraction.raw_text,
                error_message=extraction.error_message,
            )
        )
    batch.total_pages = len(rendered_pages)
    batch.raw_split_extraction_response = {"pages": header_results}
    roster_index = build_roster_index(session, batch.exam_id)
    _create_auto_split_candidates(session, batch, header_results, roster_index)
    batch.status = _split_status_for_candidates(list(batch.candidates))
    session.commit()


def _extract_headers_for_auto_split(header_crops: list[RenderedHeaderCrop]) -> list[HeaderExtractionResult]:
    if not header_crops:
        return []
    max_workers = min(settings.ocr_split_header_concurrency, len(header_crops))
    logger.info(
        "Batch split header extraction starting total_pages=%s max_workers=%s",
        len(header_crops),
        max_workers,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return sorted(executor.map(_extract_single_header_for_auto_split, header_crops), key=lambda result: result.page_no)


def _extract_single_header_for_auto_split(header_crop: RenderedHeaderCrop) -> HeaderExtractionResult:
    started_at = time.perf_counter()
    used_vision_fallback = False
    ocr_diagnostic = HeaderOCRDiagnostic(text=None, reason="not_started")
    ocr_acceptance_reason = "not_started"
    try:
        ocr_diagnostic = extract_header_text_diagnostic(header_crop.crop_path, page_hash=hash_file(header_crop.crop_path))
        header_ocr_text = ocr_diagnostic.text
        ocr_header = _header_extraction_from_ocr_text(header_crop.page_no, header_ocr_text or "")
        ocr_acceptance_reason = _header_ocr_acceptance_reason(ocr_diagnostic, ocr_header)
        if ocr_acceptance_reason == "ocr_accepted":
            header_data = ocr_header.model_dump(mode="json")
            raw_text = f"OCR_HEADER: {header_ocr_text}"
            error_message = None
        else:
            used_vision_fallback = True
            completion = call_structured_json(
                model=settings.ai_vision_model,
                system_prompt_name="split_header_detection.system.md",
                user_prompt_name="split_header_detection.user.md",
                response_model=PageHeaderExtraction,
                prompt_variables={
                    "page_no": header_crop.page_no,
                    "ocr_reference_text": format_ocr_reference_text(header_ocr_text),
                },
                image_paths=[header_crop.crop_path],
                request_profile="vision",
                route_key="vision_split_header",
            )
            header_data = completion.data.model_dump(mode="json")
            raw_text = completion.raw_text
            error_message = None
    except Exception as exc:  # noqa: BLE001 - a single page failure should not fail the whole batch
        header_data = PageHeaderExtraction().model_dump(mode="json")
        raw_text = f"ERROR: {exc}"
        error_message = str(exc)
    logger.info(
        "Batch split header extraction completed page_no=%s used_vision_fallback=%s ocr_reason=%s fallback_reason=%s ocr_cache_hit=%s ocr_text_chars=%s ocr_error=%s failed=%s duration_seconds=%.2f",
        header_crop.page_no,
        used_vision_fallback,
        ocr_diagnostic.reason,
        ocr_acceptance_reason,
        ocr_diagnostic.cache_hit,
        ocr_diagnostic.text_chars,
        ocr_diagnostic.error_message,
        error_message is not None,
        time.perf_counter() - started_at,
    )
    return HeaderExtractionResult(
        page_no=header_crop.page_no,
        page_image_path=header_crop.page_image_path,
        crop_path=header_crop.crop_path,
        extracted_text=header_crop.extracted_text,
        header_data=header_data,
        raw_text=raw_text,
        error_message=error_message,
    )


def _header_ocr_acceptance_reason(ocr_diagnostic: HeaderOCRDiagnostic, ocr_header: PageHeaderExtraction) -> str:
    if not ocr_diagnostic.text:
        return ocr_diagnostic.reason
    if not ocr_header.student_name.value and not ocr_header.student_id.value:
        return "regex_no_identity"
    if not ocr_header.student_name.value:
        return "regex_no_student_name"
    if not ocr_header.student_id.value:
        return "regex_no_student_id"
    if ocr_header.overall_confidence < settings.ocr_split_header_min_confidence:
        return "ocr_low_confidence"
    return "ocr_accepted"


def _header_extraction_from_ocr_text(page_no: int, text: str) -> PageHeaderExtraction:
    cleaned = " ".join(text.split())
    if not cleaned:
        return PageHeaderExtraction()
    student_id = _extract_student_id(cleaned)
    student_name = _extract_student_name(cleaned, student_id)
    page_number = _extract_page_number(cleaned) or page_no
    field_count = sum(1 for value in [student_name, student_id] if value)
    confidence = 0.0
    if field_count == 2:
        confidence = 0.9
    elif field_count == 1:
        confidence = 0.55
    page_confidence = 0.9 if page_number == 1 else 0.35
    return PageHeaderExtraction.model_validate(
        {
            "student_name": {"value": student_name, "confidence": confidence if student_name else 0.0},
            "student_id": {"value": student_id, "confidence": confidence if student_id else 0.0},
            "quiz_title": {"value": None, "confidence": 0.0},
            "page_number": {"value": page_number, "confidence": page_confidence},
            "is_first_page_confidence": page_confidence,
            "overall_confidence": min(confidence, page_confidence) if field_count == 2 else confidence,
        }
    )


def _extract_student_id(text: str) -> str | None:
    labelled = re.search(r"(?:学号|student\s*id|student\s*no\.?|学籍号|考号|id)[:：#\s]*([A-Za-z0-9][A-Za-z0-9_\-]{3,24})", text, flags=re.IGNORECASE)
    if labelled:
        return _clean_student_id(labelled.group(1))
    for match in re.finditer(r"\b(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9][A-Za-z0-9_\-]{5,17}\b", text):
        candidate = _clean_student_id(match.group(0))
        if candidate and not _looks_like_student_id_noise(candidate):
            return candidate
    return None


def _clean_student_id(candidate: str | None) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", candidate or "").strip("_-")
    return cleaned or None


def _looks_like_student_id_noise(candidate: str) -> bool:
    normalized = candidate.casefold().strip("_-")
    if normalized in _STUDENT_ID_NOISE_TOKENS:
        return True
    if any(token in normalized for token in _STUDENT_ID_NOISE_TOKENS) and not re.search(r"\d{3,}", normalized):
        return True
    if re.fullmatch(r"20\d{2}[-_/]?(?:0?[1-9]|1[0-2])[-_/]?(?:0?[1-9]|[12]\d|3[01])", normalized):
        return True
    if re.fullmatch(r"\d{1,3}[-_/]\d{1,3}", normalized):
        return True
    return False


def _extract_student_name(text: str, student_id: str | None) -> str | None:
    labelled = re.search(r"(?:姓名|学生|name)[:：\s]*([一-鿿A-Za-z][一-鿿A-Za-z\s·]{1,24})", text, flags=re.IGNORECASE)
    if labelled:
        return _clean_student_name(labelled.group(1), student_id)
    if student_id:
        before_id = text.split(student_id, 1)[0]
        chinese_names = re.findall(r"[一-鿿]{2,4}", before_id)
        for candidate in reversed(chinese_names):
            if candidate not in _STUDENT_NAME_NOISE_TOKENS:
                return candidate
    return None


def _extract_page_number(text: str) -> int | None:
    labelled = re.search(r"(?:页码|第\s*|page|p\.)[:：\s]*(\d{1,3})", text, flags=re.IGNORECASE)
    if labelled:
        return _clean_page_number(labelled.group(1))
    fraction = re.search(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b", text)
    if fraction:
        page_number = _clean_page_number(fraction.group(1))
        total_pages = _clean_page_number(fraction.group(2))
        if page_number is not None and total_pages is not None and page_number <= total_pages:
            return page_number
    return None


def _clean_page_number(value: str | int | None) -> int | None:
    try:
        page_number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if page_number < 1 or page_number > MAX_REASONABLE_SPLIT_PAGE_NUMBER:
        return None
    return page_number


def _clean_student_name(name: str, student_id: str | None) -> str | None:
    cleaned = re.split(r"学号|student\s*id|id|页码|page", name, flags=re.IGNORECASE)[0]
    if student_id:
        cleaned = cleaned.replace(student_id, "")
    cleaned = _clean_optional(cleaned)
    return cleaned[:24] if cleaned else None


def _create_auto_split_candidates(
    session: Session,
    batch: SubmissionBatch,
    headers: list[dict[str, Any]],
    roster_index: RosterIndex | None = None,
) -> None:
    if roster_index is None:
        roster_index = build_roster_index(session, batch.exam_id)
    starts: list[int] = []
    previous_identity: tuple[str | None, str | None] = (None, None)
    previous_page_number: int | None = None
    previous_quiz_title: str | None = None
    for index, header in enumerate(headers, start=1):
        identity = _identity_from_header(header)
        normalized_identity = _normalize_header_identity(identity)
        normalized_previous = _normalize_header_identity(previous_identity)
        page_number = _clean_page_number(_header_value(header, "page_number"))
        first_page_confidence = float(header.get("is_first_page_confidence") or 0.0)
        same_identity = _same_header_identity(normalized_identity, normalized_previous)
        identity_changed = normalized_identity != (None, None) and normalized_previous != (None, None) and not same_identity
        quiz_title = _normalize_quiz_title(_string_or_none(_header_value(header, "quiz_title")))
        quiz_continues = bool(quiz_title and previous_quiz_title and quiz_title == previous_quiz_title)
        page_continues = bool(page_number is not None and previous_page_number is not None and page_number >= previous_page_number)
        high_confidence_first_page = first_page_confidence >= SPLIT_CONFIDENCE_THRESHOLD
        page_reset = page_number == 1 and previous_page_number not in {None, 1}
        identity_missing_after_known_student = normalized_identity == (None, None) and normalized_previous != (None, None)
        continuity_guard = identity_missing_after_known_student and not page_reset and (quiz_continues or page_continues)
        is_first_page = high_confidence_first_page or page_reset
        if index == 1:
            starts.append(index)
        elif identity_changed:
            starts.append(index)
        elif is_first_page and not same_identity and not continuity_guard:
            starts.append(index)
        if normalized_identity != (None, None):
            previous_identity = identity
        if page_number is not None:
            previous_page_number = page_number
        if quiz_title:
            previous_quiz_title = quiz_title
    starts = sorted(set(starts)) or [1]
    candidate_index = 0
    for start, next_start in zip(starts, starts[1:] + [len(headers) + 1], strict=True):
        candidate_index += 1
        end = next_start - 1
        header = headers[start - 1]
        student_name, student_id = _identity_from_header(header)
        confidence = min(
            float(header.get("overall_confidence") or 0.0),
            float(header.get("is_first_page_confidence") or 0.0),
        )
        roster_match = match_roster_identity(roster_index, student_name, student_id)
        roster_entry_id: int | None = None
        review_notes_parts: list[str] = []
        if roster_match.entry is not None:
            roster_entry_id = roster_match.entry.id
            student_name = roster_match.entry.student_name or student_name
            student_id = roster_match.entry.student_id or student_id
            confidence = max(confidence, 0.9)
        elif not roster_index.is_empty():
            review_notes_parts.append("未在名单中找到匹配学生")
        needs_review = (
            confidence < SPLIT_CONFIDENCE_THRESHOLD
            or not student_name
            or not student_id
            or (roster_match.entry is None and not roster_index.is_empty())
        )
        if needs_review and not review_notes_parts:
            review_notes_parts.append("自动拆分置信度较低，需要人工确认")
        session.add(
            BatchSplitCandidate(
                batch_id=batch.id,
                candidate_index=candidate_index,
                start_page=start,
                end_page=end,
                student_name=student_name,
                student_id=student_id,
                split_confidence=confidence,
                needs_review=needs_review,
                confirmed=False,
                review_notes=" / ".join(review_notes_parts) or None,
                roster_entry_id=roster_entry_id,
            )
        )


def parse_student_identity_from_filename(filename: str) -> ParsedStudentIdentity:
    stem = Path(sanitize_filename(filename)).stem.strip()
    patterns = [
        re.compile(r"^(?P<student_id>[A-Za-z0-9]{4,})[_\-\s]+(?P<student_name>.+)$"),
        re.compile(r"^(?P<student_name>.+?)[_\-\s]+(?P<student_id>[A-Za-z0-9]{4,})$"),
    ]
    for pattern in patterns:
        match = pattern.match(stem)
        if not match:
            continue
        student_id = _clean_optional(match.groupdict().get("student_id"))
        student_name = _clean_optional(match.groupdict().get("student_name"))
        if student_id and student_name:
            return ParsedStudentIdentity(student_id=student_id, student_name=student_name, confidence=1.0)
    return ParsedStudentIdentity(student_id=None, student_name=None, confidence=0.0)


def _create_submission_from_candidate(
    session: Session,
    batch: SubmissionBatch,
    candidate: BatchSplitCandidate,
    storage_path: str | None,
) -> Submission:
    if not storage_path:
        raise BatchPipelineError("Candidate has no source PDF path")
    submission = Submission(
        exam_id=batch.exam_id,
        batch_id=batch.id,
        batch_candidate_id=candidate.id,
        student_name=candidate.student_name,
        student_id=candidate.student_id,
        original_pdf_path=storage_path,
        status=SubmissionStatus.needs_review.value if candidate.needs_review else SubmissionStatus.uploaded.value,
        source_mode=batch.mode,
        split_confidence=candidate.split_confidence,
        split_confirmed=False,
    )
    session.add(submission)
    session.flush()
    return submission


def _record_zip_pages(session: Session, batch: SubmissionBatch, relative_pdf_path: str, candidate_index: int) -> None:
    storage = get_storage_service()
    rendered_pages = render_pdf_to_images(
        storage.path_for(relative_pdf_path),
        storage.path_for(f"rendered/batches/{batch.id}/zip-candidate-{candidate_index:03d}"),
        dpi=settings.render_dpi,
    )
    next_page_no = _next_batch_page_no(session, batch.id)
    for rendered_page in rendered_pages:
        session.add(
            BatchPage(
                batch_id=batch.id,
                page_no=next_page_no,
                image_path=storage.relative_path_for(rendered_page.image_path),
                page_hash=hash_file(rendered_page.image_path),
                extracted_text=rendered_page.extracted_text,
            )
        )
        session.flush()
        next_page_no += 1


def _next_batch_page_no(session: Session, batch_id: int) -> int:
    return session.execute(select(func.coalesce(func.max(BatchPage.page_no), 0)).where(BatchPage.batch_id == batch_id)).scalar_one() + 1


def _add_failed_candidate(session: Session, batch: SubmissionBatch, index: int, filename: str, error: str) -> None:
    session.add(
        BatchSplitCandidate(
            batch_id=batch.id,
            candidate_index=index,
            start_page=1,
            end_page=1,
            split_confidence=0.0,
            needs_review=True,
            confirmed=False,
            source_filename=filename,
            review_notes="该文件无法自动处理",
            error_message=error,
        )
    )


def _clear_batch_children(session: Session, batch_id: int, *, clear_submissions: bool) -> None:
    if clear_submissions:
        session.execute(delete(Submission).where(Submission.batch_id == batch_id))
    session.execute(delete(BatchPage).where(BatchPage.batch_id == batch_id))
    session.execute(delete(BatchSplitCandidate).where(BatchSplitCandidate.batch_id == batch_id))
    session.flush()


def _validate_candidate_ranges(updates: list[BatchCandidateUpdate], total_pages: int | None) -> None:
    if not updates:
        raise BatchPipelineError("At least one non-ignored split candidate is required")
    normalized: list[tuple[int, int]] = []
    for update in updates:
        if update.start_page < 1 or update.end_page < update.start_page:
            raise BatchPipelineError("Candidate page ranges must be valid")
        if total_pages is not None and update.end_page > total_pages:
            raise BatchPipelineError("Candidate page range exceeds batch page count")
        normalized.append((update.start_page, update.end_page))
    for (_, previous_end), (next_start, _) in zip(sorted(normalized), sorted(normalized)[1:], strict=False):
        if next_start <= previous_end:
            raise BatchPipelineError("Candidate page ranges must not overlap")


def _split_status_for_candidates(candidates: list[BatchSplitCandidate]) -> str:
    active_candidates = _active_candidates(candidates)
    if not active_candidates:
        return BatchStatus.needs_split_review.value
    if any(candidate.error_message for candidate in active_candidates):
        return BatchStatus.needs_split_review.value
    if any(candidate.needs_review or not candidate.confirmed for candidate in active_candidates):
        return BatchStatus.needs_split_review.value
    return BatchStatus.split_ready.value


def _active_candidates(candidates: list[BatchSplitCandidate]) -> list[BatchSplitCandidate]:
    return [candidate for candidate in candidates if not candidate.excluded]


def _normalize_header_identity(identity: tuple[str | None, str | None]) -> tuple[str | None, str | None]:
    student_name, student_id = identity
    normalized_name = re.sub(r"\s+", "", student_name or "").casefold() or None
    normalized_id = re.sub(r"\s+", "", student_id or "").casefold() or None
    return normalized_name, normalized_id


def _normalize_quiz_title(title: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", title or "").casefold()
    return normalized or None


def _same_header_identity(
    current: tuple[str | None, str | None],
    previous: tuple[str | None, str | None],
) -> bool:
    current_name, current_id = current
    previous_name, previous_id = previous
    if current_id and previous_id:
        return current_id == previous_id
    if current_name and previous_name:
        return current_name == previous_name
    return False


def _zip_entry_escapes(filename: str) -> bool:
    path = PurePosixPath(filename)
    return path.is_absolute() or ".." in path.parts


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _header_value(header: dict[str, Any], key: str) -> Any:
    value = header.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return None


def _identity_from_header(header: dict[str, Any]) -> tuple[str | None, str | None]:
    return _clean_optional(_string_or_none(_header_value(header, "student_name"))), _clean_optional(
        _string_or_none(_header_value(header, "student_id"))
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
