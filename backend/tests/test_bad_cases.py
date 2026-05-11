from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import Exam, OcrBadCase
from app.services import bad_cases


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


def test_ocr_bad_case_model_persists_core_fields(session) -> None:
    exam = Exam(title="Midterm")
    session.add(exam)
    session.flush()
    case = OcrBadCase(
        route_key="vision_split_header",
        exam_id=exam.id,
        image_storage_path="rendered/batches/1/headers/page-001.png",
        image_hash="a" * 64,
        ocr_model="PaddleOCR-VL-1.5",
        ocr_raw_text="姓名 张三",
        trigger_reason="regex_no_student_id",
        trigger_source="auto",
    )
    session.add(case)
    session.commit()

    stored = session.execute(select(OcrBadCase)).scalar_one()

    assert stored.status == "pending"
    assert stored.redact_pii is True
    assert stored.exam_id == exam.id
    assert stored.image_storage_path.endswith("page-001.png")


def test_enqueue_inserts_and_deduplicates_by_image_hash_and_route(session) -> None:
    first_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="b" * 64,
        exam_id=None,
    )
    second_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="new text",
        ocr_error_message="later error",
        trigger_reason="ocr_request_failed",
        image_hash="b" * 64,
        exam_id=None,
    )

    assert second_id == first_id
    stored = session.get(OcrBadCase, first_id)
    assert stored.ocr_raw_text == "new text"
    assert stored.ocr_error_message == "later error"
    assert stored.trigger_reason == "ocr_request_failed"


def test_enqueue_swallows_db_failures(monkeypatch: pytest.MonkeyPatch, session) -> None:
    def fail_flush() -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(session, "flush", fail_flush)

    result = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="c" * 64,
    )

    assert result is None


def test_enqueue_failure_does_not_rollback_outer_transaction(session) -> None:
    exam = Exam(title="Keep this exam")
    session.add(exam)

    result = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash=None,
    )

    assert result is None
    session.commit()
    stored = session.execute(select(Exam).where(Exam.title == "Keep this exam")).scalar_one()
    assert stored.id == exam.id


def test_enqueue_unique_conflict_returns_existing_case_id(monkeypatch: pytest.MonkeyPatch, session) -> None:
    existing_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="z" * 64,
    )
    session.commit()
    original_execute = session.execute
    first_lookup = True

    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    def fake_execute(statement, *args, **kwargs):
        nonlocal first_lookup
        if first_lookup and "ocr_bad_cases" in str(statement):
            first_lookup = False
            return EmptyResult()
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", fake_execute)

    result = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="new text",
        ocr_error_message=None,
        trigger_reason="ocr_request_failed",
        image_hash="z" * 64,
    )

    assert result == existing_id


def test_update_bad_case_auto_triages_when_ground_truth_first_set(session) -> None:
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="d" * 64,
    )

    updated = bad_cases.update_bad_case(session, case_id, ground_truth_text="姓名 张三 学号 123456")

    assert updated.status == "triaged"
    assert updated.ground_truth_text == "姓名 张三 学号 123456"


def test_update_bad_case_rejects_ready_without_ground_truth(session) -> None:
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_split_header",
        image_storage_path="rendered/batches/1/headers/page-001.png",
        ocr_raw_text="bad text",
        ocr_error_message=None,
        trigger_reason="regex_no_student_id",
        image_hash="e" * 64,
    )

    with pytest.raises(bad_cases.BadCaseError, match="ground_truth_text"):
        bad_cases.update_bad_case(session, case_id, status="ready")


def test_export_badcases_zip_writes_jsonl_images_and_marks_exported(session) -> None:
    image_path = settings.storage_dir / "rendered/submissions/1/pages/page-001.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 80), "white").save(image_path)
    case_id = bad_cases.enqueue(
        session,
        route_key="vision_student_extraction",
        image_storage_path="rendered/submissions/1/pages/page-001.png",
        ocr_raw_text="姓名 张三 学号 12345678",
        ocr_error_message=None,
        trigger_reason="ocr_empty_text",
        image_hash="f" * 64,
    )
    bad_cases.update_bad_case(session, case_id, ground_truth_text="正确文本", status="ready")

    payload, meta = bad_cases.export_badcases_zip(session)

    assert meta["exported_count"] == 1
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        row = json.loads(archive.read("cases.jsonl").decode("utf-8").strip())
        assert row["id"] == case_id
        assert row["schema_version"] == 1
        assert row["ground_truth_text"] == "正确文本"
        assert archive.read(f"images/{case_id:05d}.png")
    assert session.get(OcrBadCase, case_id).status == "exported"
