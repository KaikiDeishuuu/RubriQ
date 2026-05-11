from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import Answer, BatchStatus, BatchUploadMode, Exam, Question, RosterEntry, Submission, SubmissionBatch, SubmissionStatus
from app.schemas.batch import BatchCandidateUpdate
from app.services import batch_pipeline
from app.services.batch_pipeline import (
    BatchPipelineError,
    confirm_batch_split,
    parse_student_identity_from_filename,
    prepare_batch_split,
    refresh_batch_grading_status,
    start_batch_grading,
    update_batch_candidates,
)
from app.services.roster import ParsedRosterEntry, replace_roster_entries


@pytest.fixture()
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        get_storage_service.cache_clear()


def _ocr_diagnostic(text: str | None, reason: str = "ocr_text_extracted"):
    return batch_pipeline.HeaderOCRDiagnostic(
        text=text,
        reason=reason if text else "no_api_key",
        text_chars=len(text or ""),
        cache_hit=False,
    )


def test_parse_student_identity_from_filename_supports_common_patterns() -> None:
    assert parse_student_identity_from_filename("20240001_Alice.pdf").student_name == "Alice"
    assert parse_student_identity_from_filename("Bob-20240002.pdf").student_id == "20240002"
    assert parse_student_identity_from_filename("unknown.pdf").confidence == 0.0


def test_zip_batch_creates_submission_and_marks_unparsed_name_for_review(session) -> None:
    exam = _create_exam(session)
    zip_path = _create_zip_with_pdfs(settings.storage_dir / "source.zip", ["20240001_Alice.pdf", "unknown.pdf"])
    batch = _create_batch(session, exam.id, BatchUploadMode.zip.value, zip_path)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert len(prepared.candidates) == 2
    assert len(prepared.submissions) == 2
    parsed_candidate = prepared.candidates[0]
    assert parsed_candidate.student_id == "20240001"
    assert parsed_candidate.student_name == "Alice"
    assert parsed_candidate.submission is not None
    assert parsed_candidate.submission.split_confirmed is False
    assert prepared.candidates[1].needs_review is True
    assert prepared.candidates[1].start_page == 2
    assert prepared.candidates[1].submission.status == SubmissionStatus.needs_review.value


def test_fixed_page_batch_marks_last_incomplete_range_for_review(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 5)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert prepared.total_pages == 5
    assert [(candidate.start_page, candidate.end_page) for candidate in prepared.candidates] == [(1, 2), (3, 4), (5, 5)]
    assert prepared.candidates[-1].needs_review is True
    assert len(prepared.pages) == 5
    assert all(page.page_hash for page in prepared.pages)


def test_candidate_update_rejects_overlapping_ranges(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepare_batch_split(session, batch.id)

    with pytest.raises(BatchPipelineError):
        update_batch_candidates(
            session,
            batch.id,
            [
                BatchCandidateUpdate(id=None, start_page=1, end_page=3, confirmed=True),
                BatchCandidateUpdate(id=None, start_page=3, end_page=4, confirmed=True),
            ],
        )


def test_candidate_update_allows_overlap_for_excluded_candidate(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepared = prepare_batch_split(session, batch.id)

    updated = update_batch_candidates(
        session,
        batch.id,
        [
            BatchCandidateUpdate(
                id=prepared.candidates[0].id,
                candidate_index=1,
                start_page=1,
                end_page=3,
                student_name="Alice",
                student_id="S001",
                confirmed=True,
            ),
            BatchCandidateUpdate(
                id=prepared.candidates[1].id,
                candidate_index=2,
                start_page=3,
                end_page=4,
                student_name="Duplicate",
                student_id="S999",
                confirmed=False,
                excluded=True,
            ),
        ],
    )

    assert updated.candidates[1].excluded is True
    assert updated.candidates[1].confirmed is False
    assert updated.status == BatchStatus.split_ready.value


def test_confirm_split_materializes_only_non_excluded_candidates(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepared = prepare_batch_split(session, batch.id)
    update_batch_candidates(
        session,
        batch.id,
        [
            BatchCandidateUpdate(
                id=prepared.candidates[0].id,
                candidate_index=1,
                start_page=1,
                end_page=4,
                student_name="Alice",
                student_id="S001",
                confirmed=True,
            ),
            BatchCandidateUpdate(
                id=prepared.candidates[1].id,
                candidate_index=2,
                start_page=3,
                end_page=4,
                excluded=True,
            ),
        ],
    )

    result = confirm_batch_split(session, batch.id)

    assert result.created_submission_count == 1
    assert len(result.batch.submissions) == 1
    assert result.batch.submissions[0].student_name == "Alice"


def test_confirm_split_rejects_all_excluded_candidates(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 2)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepared = prepare_batch_split(session, batch.id)
    update_batch_candidates(
        session,
        batch.id,
        [
            BatchCandidateUpdate(
                id=prepared.candidates[0].id,
                candidate_index=1,
                start_page=1,
                end_page=2,
                excluded=True,
            )
        ],
    )

    with pytest.raises(BatchPipelineError, match="non-ignored"):
        confirm_batch_split(session, batch.id)


def test_confirm_fixed_split_materializes_submissions(session) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepared = prepare_batch_split(session, batch.id)
    updates = [
        BatchCandidateUpdate(
            id=candidate.id,
            candidate_index=candidate.candidate_index,
            start_page=candidate.start_page,
            end_page=candidate.end_page,
            student_name=f"Student {candidate.candidate_index}",
            student_id=f"S{candidate.candidate_index:03d}",
            confirmed=True,
        )
        for candidate in prepared.candidates
    ]
    update_batch_candidates(session, batch.id, updates)

    result = confirm_batch_split(session, batch.id)

    assert result.failed_candidate_count == 0
    assert result.created_submission_count == 2
    assert result.batch.status == BatchStatus.ready_for_grading.value
    assert all(submission.split_confirmed for submission in result.batch.submissions)
    assert all(submission.original_pdf_path.endswith(".pdf") for submission in result.batch.submissions)


def test_auto_split_low_confidence_requires_review(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 2)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        page_no = kwargs["prompt_variables"]["page_no"]
        if page_no == 1:
            return _fake_completion("Alice", "S001", 0.95)
        return _fake_completion("Bob", "S002", 0.4)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic(None))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert len(prepared.candidates) == 2
    assert prepared.candidates[0].needs_review is False
    assert prepared.candidates[1].needs_review is True
    assert seen_route_keys == ["vision_split_header", "vision_split_header"]


def test_auto_split_high_confidence_ocr_skips_vision(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 1)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)

    def fake_call_structured_json(**_kwargs):
        pytest.fail("vision fallback should not be called")

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic("姓名 张三 学号 123456 页码 1"))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert len(prepared.candidates) == 1
    assert prepared.candidates[0].student_name == "张三"
    assert prepared.candidates[0].student_id == "123456"
    assert prepared.candidates[0].needs_review is False
    assert prepared.pages[0].raw_ai_response == "OCR_HEADER: 姓名 张三 学号 123456 页码 1"


def test_auto_split_keeps_same_identity_pages_together_when_page_number_is_one(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 2)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)
    ocr_texts = iter([
        "姓名 张三 学号 123456 页码 1",
        "姓名 张三 学号 123456 页码 1",
    ])

    def fake_call_structured_json(**_kwargs):
        pytest.fail("high confidence OCR should skip vision fallback")

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic(next(ocr_texts)))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert len(prepared.candidates) == 1
    assert prepared.candidates[0].start_page == 1
    assert prepared.candidates[0].end_page == 2
    assert prepared.candidates[0].student_name == "张三"
    assert prepared.candidates[0].student_id == "123456"


def test_auto_split_ignores_unlabelled_noise_as_student_id(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 1)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)

    def fake_call_structured_json(**_kwargs):
        return _fake_completion("Alice", "S001", 0.95)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic("QuizOCR PAGEHEADER 2026-05-09 Page 1/1"))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.candidates[0].student_id == "S001"
    assert prepared.pages[0].raw_ai_response != "OCR_HEADER: QuizOCR PAGEHEADER 2026-05-09 Page 1/1"



def test_auto_split_page_failure_keeps_batch_reviewable(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 2)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)

    def fake_call_structured_json(**kwargs):
        if kwargs["prompt_variables"]["page_no"] == 2:
            raise RuntimeError("provider failed")
        return _fake_completion("Alice", "S001", 0.95)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic(None))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert len(prepared.pages) == 2
    assert prepared.pages[1].error_message == "provider failed"
    assert len(prepared.candidates) == 1
    assert prepared.candidates[0].end_page == 2



def test_auto_split_keeps_missing_identity_continuation_with_same_quiz_and_page_order(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 2)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)

    def fake_call_structured_json(**kwargs):
        page_no = kwargs["prompt_variables"]["page_no"]
        if page_no == 1:
            return _fake_completion("Alice", "S001", 0.95, page_number=1)
        return _fake_completion(None, None, 0.8, page_number=2)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic(None))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert len(prepared.candidates) == 1
    assert prepared.candidates[0].start_page == 1
    assert prepared.candidates[0].end_page == 2



def test_auto_split_starts_new_review_candidate_on_missing_identity_page_reset(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 3)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)

    def fake_call_structured_json(**kwargs):
        page_no = kwargs["prompt_variables"]["page_no"]
        if page_no == 1:
            return _fake_completion("Alice", "S001", 0.95, page_number=1)
        if page_no == 2:
            return _fake_completion("Alice", "S001", 0.95, page_number=2)
        return _fake_completion(None, None, 0.85, page_number=1)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic(None))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert [(candidate.start_page, candidate.end_page) for candidate in prepared.candidates] == [(1, 2), (3, 3)]
    assert prepared.candidates[1].needs_review is True



def test_header_ocr_acceptance_reason_reports_regex_failures_and_low_confidence() -> None:
    no_identity = batch_pipeline._header_extraction_from_ocr_text(1, "QuizOCR PAGEHEADER 2026-05-09 Page 1/1")
    name_only = batch_pipeline._header_extraction_from_ocr_text(1, "姓名 Alice")
    id_only = batch_pipeline._header_extraction_from_ocr_text(1, "学号 123456")
    high_confidence = batch_pipeline._header_extraction_from_ocr_text(2, "姓名 张三 学号 123456 页码 2")

    assert batch_pipeline._header_ocr_acceptance_reason(_ocr_diagnostic("noise"), no_identity) == "regex_no_identity"
    assert batch_pipeline._header_ocr_acceptance_reason(_ocr_diagnostic("姓名 Alice"), name_only) == "regex_no_student_id"
    assert batch_pipeline._header_ocr_acceptance_reason(_ocr_diagnostic("学号 123456"), id_only) == "regex_no_student_name"
    assert batch_pipeline._header_ocr_acceptance_reason(_ocr_diagnostic("姓名 张三 学号 123456 页码 2"), high_confidence) == "ocr_low_confidence"


def test_auto_split_low_confidence_ocr_falls_back_to_vision(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 1)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)
    seen_prompt_variables: list[dict] = []

    def fake_call_structured_json(**kwargs):
        seen_prompt_variables.append(kwargs.get("prompt_variables"))
        return _fake_completion("Alice", "S001", 0.95)

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic("姓名 Alice"))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", fake_call_structured_json)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.candidates[0].student_name == "Alice"
    assert prepared.candidates[0].student_id == "S001"
    assert "OCR reference text" in seen_prompt_variables[0]["ocr_reference_text"]
    assert "姓名 Alice" in seen_prompt_variables[0]["ocr_reference_text"]


def test_auto_split_header_enqueues_rejected_ocr_bad_case(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 1)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_auto.value, source_pdf)
    calls: list[dict] = []

    monkeypatch.setattr(batch_pipeline, "extract_header_text_diagnostic", lambda *_args, **_kwargs: _ocr_diagnostic("姓名 Alice"))
    monkeypatch.setattr(batch_pipeline, "call_structured_json", lambda **_kwargs: _fake_completion("Alice", "S001", 0.95))
    monkeypatch.setattr(batch_pipeline.bad_cases, "enqueue", lambda _session=None, **kwargs: calls.append(kwargs) or 1)

    prepared = prepare_batch_split(session, batch.id)

    assert len(prepared.pages) == 1
    assert calls[0]["route_key"] == "vision_split_header"
    assert calls[0]["trigger_reason"] == "regex_no_student_id"
    assert calls[0]["image_storage_path"].endswith("page-001.png")
    assert calls[0]["batch_id"] == batch.id
    assert calls[0]["batch_page_id"] == prepared.pages[0].id


def test_auto_split_header_extraction_uses_configured_concurrency(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen_workers: list[int] = []

    class InlineExecutor:
        def __init__(self, max_workers: int) -> None:
            seen_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def map(self, func, items):
            return [func(item) for item in items]

    def fake_extract_single_header(header_crop):
        return batch_pipeline.HeaderExtractionResult(
            page_no=header_crop.page_no,
            page_image_path=header_crop.page_image_path,
            crop_path=header_crop.crop_path,
            extracted_text=header_crop.extracted_text,
            header_data={"page_number": {"value": header_crop.page_no, "confidence": 1.0}},
            raw_text="{}",
            error_message=None,
        )

    monkeypatch.setattr(settings, "ocr_split_header_concurrency", 2)
    monkeypatch.setattr(batch_pipeline, "ThreadPoolExecutor", InlineExecutor)
    monkeypatch.setattr(batch_pipeline, "_extract_single_header_for_auto_split", fake_extract_single_header)
    header_crops = [
        batch_pipeline.RenderedHeaderCrop(
            page_no=page_no,
            page_image_path=tmp_path / f"page-{page_no}.png",
            crop_path=tmp_path / f"crop-{page_no}.png",
            extracted_text="",
        )
        for page_no in [3, 1, 2]
    ]

    results = batch_pipeline._extract_headers_for_auto_split(header_crops)

    assert seen_workers == [2]
    assert [result.page_no for result in results] == [1, 2, 3]


def test_start_batch_grading_rejects_exam_without_gradable_questions(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = Exam(title="No Questions")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.uploaded.value)
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    with pytest.raises(BatchPipelineError, match="parse the rubric"):
        start_batch_grading(session, batch.id)

    assert queued_ids == []
    assert session.get(Submission, submission.id).status == SubmissionStatus.uploaded.value
    assert session.get(SubmissionBatch, batch.id).status == BatchStatus.ready_for_grading.value



def test_start_batch_grading_only_queues_uploaded_and_failed_submissions(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    statuses = [
        SubmissionStatus.uploaded.value,
        SubmissionStatus.failed.value,
        SubmissionStatus.graded.value,
        SubmissionStatus.needs_review.value,
        SubmissionStatus.grading.value,
    ]
    submissions = [_create_submission(session, exam.id, batch.id, status) for status in statuses]
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    updated_batch, queued_count = start_batch_grading(session, batch.id)

    assert queued_count == 2
    assert queued_ids == [submissions[0].id, submissions[1].id]
    assert updated_batch.status == BatchStatus.grading.value
    assert session.get(Submission, submissions[0].id).status == SubmissionStatus.processing.value
    assert session.get(Submission, submissions[1].id).status == SubmissionStatus.processing.value
    assert session.get(Submission, submissions[2].id).status == SubmissionStatus.graded.value


def test_refresh_batch_grading_status_marks_completed_when_all_finished(session) -> None:
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    _create_submission(session, exam.id, batch.id, SubmissionStatus.needs_review.value)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    assert updated_batch.status == BatchStatus.completed.value


def test_refresh_batch_grading_status_marks_completed_with_errors_for_failed_submissions(session) -> None:
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    _create_submission(session, exam.id, batch.id, SubmissionStatus.failed.value)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    assert updated_batch.status == BatchStatus.completed_with_errors.value


def test_start_batch_grading_requeues_stale_active_submission(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_submission_seconds", 600)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    stale_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.grading.value)
    _make_stale(stale_submission)
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    updated_batch, queued_count = start_batch_grading(session, batch.id)

    assert queued_count == 1
    assert queued_ids == [stale_submission.id]
    assert updated_batch.status == BatchStatus.grading.value
    assert session.get(Submission, stale_submission.id).status == SubmissionStatus.processing.value


def test_refresh_batch_grading_status_marks_stale_active_submission_failed(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_submission_seconds", 600)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    stale_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.grading.value)
    _make_stale(stale_submission)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    stored_submission = session.get(Submission, stale_submission.id)
    assert stored_submission.status == SubmissionStatus.failed.value
    assert stored_submission.error_message == "Submission processing timed out or worker stopped"
    assert updated_batch.status == BatchStatus.completed_with_errors.value


def test_start_batch_grading_refreshes_status_when_no_submissions_are_queued(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    _create_submission(session, exam.id, batch.id, SubmissionStatus.needs_review.value)
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    updated_batch, queued_count = start_batch_grading(session, batch.id)

    assert queued_count == 0
    assert queued_ids == []
    assert updated_batch.status == BatchStatus.completed.value


def _make_stale(row, seconds: int = 3600) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    row.updated_at = stale_at.replace(tzinfo=None)


def _create_exam(session) -> Exam:
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    session.add(Question(exam_id=exam.id, question_no="1", title="Question 1"))
    session.commit()
    return exam


def _seed_roster(session, exam_id: int, entries: list[tuple[str | None, str | None]]) -> list[RosterEntry]:
    parsed = [ParsedRosterEntry(name, sid, source="manual") for name, sid in entries]
    replace_roster_entries(session, exam_id, parsed, source="manual")
    session.commit()
    return list(
        session.query(RosterEntry)
        .filter(RosterEntry.exam_id == exam_id)
        .order_by(RosterEntry.order_index)
    )


def test_fixed_page_batch_auto_binds_roster_entries(session) -> None:
    exam = _create_exam(session)
    roster = _seed_roster(
        session,
        exam.id,
        [("张三", "20240101"), ("李四", "20240102"), ("王五", "20240103")],
    )
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 6)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)

    prepared = prepare_batch_split(session, batch.id)

    # All candidates auto-bound and data-complete, but still await teacher confirmation
    assert prepared.status == BatchStatus.needs_split_review.value
    assert [(c.start_page, c.end_page) for c in prepared.candidates] == [(1, 2), (3, 4), (5, 6)]
    assert [c.student_name for c in prepared.candidates] == ["张三", "李四", "王五"]
    assert [c.student_id for c in prepared.candidates] == ["20240101", "20240102", "20240103"]
    assert [c.roster_entry_id for c in prepared.candidates] == [entry.id for entry in roster]
    assert all(not c.needs_review for c in prepared.candidates)
    assert all(not c.confirmed for c in prepared.candidates)


def test_fixed_page_batch_marks_review_when_roster_size_mismatches(session) -> None:
    exam = _create_exam(session)
    _seed_roster(session, exam.id, [("张三", "20240101")])  # only 1 entry, expect 3 candidates
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 6)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert all(c.needs_review for c in prepared.candidates)
    assert prepared.candidates[0].student_name == "张三"
    assert prepared.candidates[1].student_name is None
    assert prepared.candidates[1].roster_entry_id is None
    assert prepared.candidates[1].review_notes is not None


def test_update_candidates_snaps_student_fields_to_roster_entry(session) -> None:
    exam = _create_exam(session)
    roster = _seed_roster(session, exam.id, [("张三", "20240101"), ("李四", "20240102")])
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepare_batch_split(session, batch.id)

    candidate_ids = [c.id for c in batch.candidates]
    updated = update_batch_candidates(
        session,
        batch.id,
        [
            BatchCandidateUpdate(id=candidate_ids[0], start_page=1, end_page=2, confirmed=True, roster_entry_id=roster[1].id, student_name="错名", student_id="错号"),
            BatchCandidateUpdate(id=candidate_ids[1], start_page=3, end_page=4, confirmed=True, roster_entry_id=roster[0].id),
        ],
    )

    by_idx = {c.candidate_index: c for c in updated.candidates}
    assert by_idx[1].student_name == "李四"
    assert by_idx[1].student_id == "20240102"
    assert by_idx[1].roster_entry_id == roster[1].id
    assert by_idx[2].student_name == "张三"
    assert by_idx[2].roster_entry_id == roster[0].id


def test_update_candidates_rejects_duplicate_roster_entry_ids(session) -> None:
    exam = _create_exam(session)
    roster = _seed_roster(session, exam.id, [("张三", "20240101"), ("李四", "20240102")])
    source_pdf = settings.storage_dir / "combined.pdf"
    _create_pdf(source_pdf, 4)
    batch = _create_batch(session, exam.id, BatchUploadMode.combined_fixed.value, source_pdf, pages_per_submission=2)
    prepare_batch_split(session, batch.id)
    ids = [c.id for c in batch.candidates]

    with pytest.raises(BatchPipelineError):
        update_batch_candidates(
            session,
            batch.id,
            [
                BatchCandidateUpdate(id=ids[0], start_page=1, end_page=2, confirmed=True, roster_entry_id=roster[0].id),
                BatchCandidateUpdate(id=ids[1], start_page=3, end_page=4, confirmed=True, roster_entry_id=roster[0].id),
            ],
        )


def test_zip_batch_overrides_filename_identity_with_roster_match(session) -> None:
    exam = _create_exam(session)
    _seed_roster(session, exam.id, [("Alice Official", "20240001")])
    zip_path = _create_zip_with_pdfs(settings.storage_dir / "source.zip", ["20240001_Alice.pdf"])
    batch = _create_batch(session, exam.id, BatchUploadMode.zip.value, zip_path)

    prepared = prepare_batch_split(session, batch.id)

    candidate = prepared.candidates[0]
    assert candidate.student_name == "Alice Official"
    assert candidate.student_id == "20240001"
    assert candidate.roster_entry_id is not None
    assert not candidate.needs_review


def _create_batch(session, exam_id: int, mode: str, source_path: Path, pages_per_submission: int | None = None) -> SubmissionBatch:
    from app.storage.local import get_storage_service

    storage = get_storage_service()
    storage.root_dir.mkdir(parents=True, exist_ok=True)
    relative_path = source_path.relative_to(storage.root_dir) if source_path.is_relative_to(storage.root_dir) else Path(source_path.name)
    stored = storage.save_bytes(str(relative_path), source_path.read_bytes())
    batch = SubmissionBatch(
        exam_id=exam_id,
        mode=mode,
        status=BatchStatus.uploaded.value,
        source_filename=source_path.name,
        source_storage_path=stored.relative_path,
        pages_per_submission=pages_per_submission,
    )
    session.add(batch)
    session.commit()
    return batch


def _create_submission(session, exam_id: int, batch_id: int, status: str) -> Submission:
    submission = Submission(
        exam_id=exam_id,
        batch_id=batch_id,
        student_name="Student",
        student_id="S001",
        original_pdf_path=f"submissions/{status}.pdf",
        status=status,
        split_confirmed=True,
    )
    session.add(submission)
    session.flush()
    return submission


def _create_pdf(path: Path, page_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for index in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}")
        document.save(str(path))


def _create_zip_with_pdfs(path: Path, filenames: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for filename in filenames:
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), filename)
                pdf_bytes = document.tobytes()
            archive.writestr(filename, pdf_bytes)
    return path


def _fake_completion(student_name: str | None, student_id: str | None, confidence: float, page_number: int = 1):
    from types import SimpleNamespace

    from app.schemas.ai import PageHeaderExtraction, PageHeaderField

    data = PageHeaderExtraction(
        student_name=PageHeaderField(value=student_name, confidence=confidence if student_name else 0.0),
        student_id=PageHeaderField(value=student_id, confidence=confidence if student_id else 0.0),
        quiz_title=PageHeaderField(value="Quiz", confidence=confidence),
        page_number=PageHeaderField(value=page_number, confidence=confidence),
        is_first_page_confidence=confidence if page_number == 1 else 0.2,
        overall_confidence=confidence,
    )
    return SimpleNamespace(data=data, raw_text=data.model_dump_json())


def test_start_batch_grading_dispatches_chunks(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_batch_size", 2)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    submissions = [
        _create_submission(session, exam.id, batch.id, SubmissionStatus.uploaded.value)
        for _ in range(5)
    ]
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    updated_batch, queued_count = start_batch_grading(session, batch.id)

    assert queued_count == 2
    assert len(queued_ids) == 2
    assert queued_ids == sorted(s.id for s in submissions)[:2]
    assert updated_batch.status == BatchStatus.grading.value

    # First chunk completes; refresh should dispatch the next chunk
    for sid in queued_ids:
        sub = session.get(Submission, sid)
        sub.status = SubmissionStatus.graded.value
    session.commit()

    refresh_batch_grading_status(session, batch.id)

    assert len(queued_ids) == 4  # second chunk dispatched
    assert queued_ids[2:] == sorted(s.id for s in submissions)[2:4]


def test_start_batch_grading_requires_confirmed_roster(session) -> None:
    exam = _create_exam(session)
    exam.roster_status = "needs_review"
    session.commit()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.commit()

    with pytest.raises(BatchPipelineError, match="考试名单"):
        start_batch_grading(session, batch.id)


def test_batch_variance_review_skips_teacher_reviewed_answers(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_review_variance_min_answers", 2)
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_review_variance_range_ratio", 0.1)
    exam = _create_exam(session)
    question = exam.questions[0]
    question.max_score = 10
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.completed.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    reviewed_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    pending_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    reviewed_answer = Answer(
        submission_id=reviewed_submission.id,
        question_id=question.id,
        extracted_answer="reviewed",
        score=10,
        max_score=10,
        review_decision="teacher_reviewed",
    )
    pending_answer = Answer(
        submission_id=pending_submission.id,
        question_id=question.id,
        extracted_answer="pending",
        score=0,
        max_score=10,
    )
    session.add_all([reviewed_answer, pending_answer])
    session.commit()

    answer_ids = batch_pipeline._batch_variance_review_answer_ids(session, batch.id)

    assert answer_ids == [pending_answer.id]


def test_refresh_batch_grading_status_marks_stale_batch_review_failed(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_review_enabled", True)
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_batch_review_seconds", 1800)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="running",
    )
    session.add(batch)
    session.flush()
    _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    _make_stale(batch, seconds=3600)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    stored_batch = session.get(SubmissionBatch, batch.id)
    assert stored_batch.ai_review_status == "failed"
    assert stored_batch.ai_review_error_message == "Batch grading review timed out or worker stopped"
    assert updated_batch.status == BatchStatus.completed_with_errors.value


def test_batch_review_failure_stores_sanitized_error(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_review_enabled", True)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.completed.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.commit()
    monkeypatch.setattr(batch_pipeline, "_batch_variance_review_answer_ids", lambda *_args: [1])

    def fail_review(*_args, **_kwargs):
        raise RuntimeError("provider traceback leaked bearer secret-token")

    monkeypatch.setattr(batch_pipeline, "review_answer_with_strong_model", fail_review)

    with pytest.raises(RuntimeError):
        batch_pipeline.review_batch_grading(session, batch.id)

    stored_batch = session.get(SubmissionBatch, batch.id)
    assert stored_batch.ai_review_status == "failed"
    assert stored_batch.ai_review_error_message == "Batch grading review failed"
    assert stored_batch.status == BatchStatus.completed_with_errors.value
