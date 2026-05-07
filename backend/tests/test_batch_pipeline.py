from __future__ import annotations

import zipfile
from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import BatchStatus, BatchUploadMode, Exam, SubmissionBatch, SubmissionStatus
from app.schemas.batch import BatchCandidateUpdate
from app.services import batch_pipeline
from app.services.batch_pipeline import (
    BatchPipelineError,
    confirm_batch_split,
    parse_student_identity_from_filename,
    prepare_batch_split,
    update_batch_candidates,
)


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
    responses = iter([
        _fake_completion("Alice", "S001", 0.95),
        _fake_completion("Bob", "S002", 0.4),
    ])
    monkeypatch.setattr(batch_pipeline, "call_structured_json", lambda **_kwargs: next(responses))

    prepared = prepare_batch_split(session, batch.id)

    assert prepared.status == BatchStatus.needs_split_review.value
    assert len(prepared.candidates) == 2
    assert prepared.candidates[0].needs_review is False
    assert prepared.candidates[1].needs_review is True


def _create_exam(session) -> Exam:
    exam = Exam(title="Sample")
    session.add(exam)
    session.commit()
    return exam


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


def _fake_completion(student_name: str, student_id: str, confidence: float):
    from types import SimpleNamespace

    from app.schemas.ai import PageHeaderExtraction, PageHeaderField

    data = PageHeaderExtraction(
        student_name=PageHeaderField(value=student_name, confidence=confidence),
        student_id=PageHeaderField(value=student_id, confidence=confidence),
        quiz_title=PageHeaderField(value="Quiz", confidence=confidence),
        page_number=PageHeaderField(value=1, confidence=confidence),
        is_first_page_confidence=confidence,
        overall_confidence=confidence,
    )
    return SimpleNamespace(data=data, raw_text=data.model_dump_json())
