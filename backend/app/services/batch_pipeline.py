from __future__ import annotations

import re
import zipfile
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
from app.services.pipeline import _to_decimal, review_answer_with_strong_model
from app.services.pdf import crop_top_region, get_pdf_page_count, hash_file, render_pdf_to_images, split_pdf_pages
from app.storage.local import get_storage_service
from app.utils.files import PDF_SIGNATURE, sanitize_filename

SPLIT_CONFIDENCE_THRESHOLD = 0.75
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
        batch.status = BatchStatus.failed.value
        batch.error_message = str(exc)
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
    _validate_candidate_ranges(updates, batch.total_pages)
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
        candidate.confirmed = update.confirmed
        candidate.needs_review = not update.confirmed or not candidate.student_name or not candidate.student_id
        if update.confirmed and candidate.split_confidence < SPLIT_CONFIDENCE_THRESHOLD:
            candidate.needs_review = False
    batch.split_version += 1
    batch.status = BatchStatus.split_ready.value if all(candidate.confirmed for candidate in batch.candidates) else _split_status_for_candidates(list(batch.candidates))
    session.commit()
    return load_batch_detail(session, batch.id)


def confirm_batch_split(session: Session, batch_id: int) -> BatchConfirmResult:
    batch = load_batch_detail(session, batch_id)
    if not batch.candidates:
        raise BatchPipelineError("No split candidates are available for confirmation")
    unconfirmed = [candidate for candidate in batch.candidates if not candidate.confirmed]
    if unconfirmed:
        raise BatchPipelineError("All split candidates must be confirmed before grading")
    invalid = [candidate for candidate in batch.candidates if not candidate.student_name or not candidate.student_id]
    if invalid:
        raise BatchPipelineError("All confirmed split candidates must have student name and ID")

    batch.status = BatchStatus.materializing.value
    session.commit()

    created_count = 0
    failed_count = 0
    if batch.mode == BatchUploadMode.zip.value:
        for candidate in batch.candidates:
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
                candidate.error_message = str(exc)
                failed_count += 1
            session.flush()
    else:
        storage = get_storage_service()
        source_path = storage.path_for(batch.source_storage_path)
        output_dir = storage.path_for(f"exams/{batch.exam_id}/batches/{batch.id}/submissions")
        page_ranges = [(candidate.start_page, candidate.end_page) for candidate in batch.candidates]
        try:
            split_paths = split_pdf_pages(source_path, page_ranges, output_dir)
        except Exception as exc:
            batch.status = BatchStatus.failed.value
            batch.error_message = str(exc)
            session.commit()
            raise BatchPipelineError(f"Failed to split combined PDF: {exc}") from exc
        for candidate, split_path in zip(batch.candidates, split_paths, strict=True):
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
                candidate.error_message = str(exc)
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
    from app.workers.tasks import process_submission_task

    batch = load_batch_detail(session, batch_id)
    if batch.status not in {BatchStatus.ready_for_grading.value, BatchStatus.completed_with_errors.value}:
        raise BatchPipelineError("Batch split must be confirmed before grading")
    _ensure_exam_has_gradable_questions(session, batch.exam_id)
    queued_submission_ids: list[int] = []
    for submission in batch.submissions:
        if not submission.split_confirmed:
            continue
        if submission.status not in STARTABLE_SUBMISSION_STATUSES:
            continue
        claimed = session.execute(
            sa_update(Submission)
            .where(Submission.id == submission.id, Submission.status.in_(STARTABLE_SUBMISSION_STATUSES))
            .values(status=SubmissionStatus.processing.value, error_message=None)
        ).rowcount
        if claimed:
            queued_submission_ids.append(submission.id)
    if queued_submission_ids:
        batch.status = BatchStatus.grading.value
        session.commit()
        for submission_id in queued_submission_ids:
            process_submission_task.delay(submission_id)
    else:
        refresh_batch_grading_status(session, batch.id)
    return load_batch_detail(session, batch.id), len(queued_submission_ids)


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
    elif any(submission.status == SubmissionStatus.failed.value for submission in submissions):
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
        batch = load_batch_detail(session, batch_id)
        batch.ai_review_status = "failed"
        batch.ai_review_error_message = str(exc)
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
        scores = [answer.fast_score if answer.fast_score is not None else answer.score for answer in question_answers]
        score_range = max(scores) - min(scores)
        if score_range <= _to_decimal(float(max_score) * settings.ai_grading_review_variance_range_ratio):
            continue
        review_answer_ids.extend(answer.id for answer in question_answers if answer.review_score is None)
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
    candidate_count = 0
    failed_count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            if _zip_entry_escapes(info.filename):
                candidate_count += 1
                _add_failed_candidate(session, batch, candidate_count, info.filename, "ZIP entry path is not allowed")
                failed_count += 1
                continue
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
                needs_review = identity.confidence < 1.0 or not identity.student_id or not identity.student_name
                first_preview_page = _next_batch_page_no(session, batch.id)
                pdf_page_count = get_pdf_page_count(stored.absolute_path)
                candidate = BatchSplitCandidate(
                    batch_id=batch.id,
                    candidate_index=candidate_count,
                    start_page=first_preview_page,
                    end_page=first_preview_page + pdf_page_count - 1,
                    student_name=identity.student_name,
                    student_id=identity.student_id,
                    split_confidence=identity.confidence,
                    needs_review=needs_review,
                    confirmed=False,
                    source_filename=original_name,
                    source_storage_path=stored.relative_path,
                    review_notes="文件名无法可靠解析学生信息" if needs_review else None,
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
    batch.status = BatchStatus.needs_split_review.value if failed_count or any(c.needs_review for c in batch.candidates) else BatchStatus.split_ready.value
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
    candidate_index = 0
    for start_page in range(1, len(rendered_pages) + 1, batch.pages_per_submission):
        candidate_index += 1
        end_page = min(start_page + batch.pages_per_submission - 1, len(rendered_pages))
        incomplete = (end_page - start_page + 1) != batch.pages_per_submission
        session.add(
            BatchSplitCandidate(
                batch_id=batch.id,
                candidate_index=candidate_index,
                start_page=start_page,
                end_page=end_page,
                split_confidence=0.65 if incomplete else 0.9,
                needs_review=incomplete,
                confirmed=False,
                review_notes="总页数不能被每份页数整除，需要确认最后一段" if incomplete else None,
            )
        )
    batch.status = BatchStatus.needs_split_review.value if len(rendered_pages) % batch.pages_per_submission else BatchStatus.split_ready.value
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
    header_results: list[dict[str, Any]] = []
    for rendered_page in rendered_pages:
        crop_path = crop_top_region(
            rendered_page.image_path,
            storage.path_for(f"rendered/batches/{batch.id}/headers/page-{rendered_page.page_no:03d}.png"),
        )
        try:
            completion = call_structured_json(
                model=settings.ai_vision_model,
                system_prompt_name="split_header_detection.system.md",
                user_prompt_name="split_header_detection.user.md",
                response_model=PageHeaderExtraction,
                prompt_variables={"page_no": rendered_page.page_no},
                image_paths=[crop_path],
                request_profile="vision",
                route_key="vision_split_header",
            )
            header_data = completion.data.model_dump(mode="json")
            raw_text = completion.raw_text
            error_message = None
        except Exception as exc:
            header_data = PageHeaderExtraction().model_dump(mode="json")
            raw_text = f"ERROR: {exc}"
            error_message = str(exc)
        header_results.append(header_data)
        session.add(
            BatchPage(
                batch_id=batch.id,
                page_no=rendered_page.page_no,
                image_path=storage.relative_path_for(rendered_page.image_path),
                page_hash=hash_file(rendered_page.image_path),
                extracted_text=rendered_page.extracted_text,
                header_extraction_json=header_data,
                raw_ai_response=raw_text,
                error_message=error_message,
            )
        )
    batch.total_pages = len(rendered_pages)
    batch.raw_split_extraction_response = {"pages": header_results}
    _create_auto_split_candidates(session, batch, header_results)
    batch.status = _split_status_for_candidates(list(batch.candidates))
    session.commit()


def _create_auto_split_candidates(session: Session, batch: SubmissionBatch, headers: list[dict[str, Any]]) -> None:
    starts: list[int] = []
    previous_identity: tuple[str | None, str | None] = (None, None)
    for index, header in enumerate(headers, start=1):
        identity = _identity_from_header(header)
        page_number = _header_value(header, "page_number")
        first_page_confidence = float(header.get("is_first_page_confidence") or 0.0)
        is_first_page = first_page_confidence >= SPLIT_CONFIDENCE_THRESHOLD or str(page_number or "").strip() in {"1", "1.0"}
        identity_changed = index == 1 or (identity != (None, None) and identity != previous_identity)
        if index == 1 or is_first_page or identity_changed:
            starts.append(index)
        if identity != (None, None):
            previous_identity = identity
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
        needs_review = confidence < SPLIT_CONFIDENCE_THRESHOLD or not student_name or not student_id
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
                review_notes="自动拆分置信度较低，需要人工确认" if needs_review else None,
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
        raise BatchPipelineError("At least one split candidate is required")
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
    if any(candidate.error_message for candidate in candidates):
        return BatchStatus.needs_split_review.value
    if any(candidate.needs_review or not candidate.confirmed for candidate in candidates):
        return BatchStatus.needs_split_review.value
    return BatchStatus.split_ready.value


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
