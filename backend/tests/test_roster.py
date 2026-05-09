from __future__ import annotations

import io
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import Exam, RosterEntry
from app.schemas.exam import RosterEntryInput
from app.services.roster import (
    ParsedRosterEntry,
    RosterError,
    build_roster_index,
    confirm_roster,
    match_roster_identity,
    parse_roster_table,
    replace_roster_entries,
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


def _create_exam(session) -> Exam:
    exam = Exam(title="Demo Exam")
    session.add(exam)
    session.commit()
    return exam


def test_parse_roster_table_csv_with_chinese_headers() -> None:
    csv_text = "姓名,学号\n张三,20240101\n李四,20240102\n,\n王五,20240103\n"
    entries = parse_roster_table(csv_text.encode("utf-8"), "csv")
    assert [(entry.student_name, entry.student_id) for entry in entries] == [
        ("张三", "20240101"),
        ("李四", "20240102"),
        ("王五", "20240103"),
    ]
    assert all(entry.source == "csv" for entry in entries)


def test_parse_roster_table_csv_english_headers_without_header_falls_back() -> None:
    csv_text = "Alice,A001\nBob,A002\n"
    entries = parse_roster_table(csv_text.encode("utf-8"), "csv")
    assert [(entry.student_name, entry.student_id) for entry in entries] == [
        ("Alice", "A001"),
        ("Bob", "A002"),
    ]


def test_parse_roster_table_xlsx() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["学号", "姓名"])
    sheet.append(["20240101", "张三"])
    sheet.append(["20240102", "李四"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    entries = parse_roster_table(buffer.getvalue(), "xlsx")
    assert [(entry.student_name, entry.student_id) for entry in entries] == [
        ("张三", "20240101"),
        ("李四", "20240102"),
    ]


def test_parse_roster_table_unsupported_suffix_raises() -> None:
    with pytest.raises(RosterError):
        parse_roster_table(b"name,id", "txt")


def test_replace_roster_entries_resets_order_and_status(session) -> None:
    exam = _create_exam(session)
    replace_roster_entries(
        session,
        exam.id,
        [
            ParsedRosterEntry("张三", "20240101", source="manual"),
            ParsedRosterEntry(None, None, source="manual"),  # filtered
            ParsedRosterEntry("李四", "20240102", source="manual"),
        ],
        source="manual",
    )
    session.commit()
    entries = session.query(RosterEntry).order_by(RosterEntry.order_index).all()
    assert [(entry.order_index, entry.student_name, entry.student_id) for entry in entries] == [
        (0, "张三", "20240101"),
        (1, "李四", "20240102"),
    ]
    assert exam.roster_status == "needs_review"

    # Re-replacing should reset order_index to start from 0 again.
    replace_roster_entries(
        session,
        exam.id,
        [RosterEntryInput(student_name="王五", student_id="20240103")],
        source="manual",
    )
    session.commit()
    entries = session.query(RosterEntry).order_by(RosterEntry.order_index).all()
    assert [(entry.order_index, entry.student_name, entry.student_id) for entry in entries] == [
        (0, "王五", "20240103"),
    ]


def test_replace_roster_entries_empty_raises(session) -> None:
    exam = _create_exam(session)
    with pytest.raises(RosterError):
        replace_roster_entries(session, exam.id, [], source="manual")


def test_match_roster_identity_prefers_id_then_name(session) -> None:
    exam = _create_exam(session)
    replace_roster_entries(
        session,
        exam.id,
        [
            ParsedRosterEntry("张三", "20240101"),
            ParsedRosterEntry("李四", "20240102"),
        ],
        source="manual",
    )
    session.commit()
    index = build_roster_index(session, exam.id)
    matched_by_id = match_roster_identity(index, student_name="错名", student_id="20240102")
    assert matched_by_id.entry is not None
    assert matched_by_id.match_kind == "id"
    assert matched_by_id.entry.student_name == "李四"

    matched_by_name = match_roster_identity(index, student_name=" 张三 ", student_id=None)
    assert matched_by_name.entry is not None
    assert matched_by_name.match_kind == "name"

    missing = match_roster_identity(index, student_name="陌生", student_id="999")
    assert missing.entry is None
    assert missing.match_kind == "none"


def test_match_roster_identity_is_case_and_whitespace_insensitive(session) -> None:
    exam = _create_exam(session)
    replace_roster_entries(
        session,
        exam.id,
        [ParsedRosterEntry("Alice", "A001")],
        source="manual",
    )
    session.commit()
    index = build_roster_index(session, exam.id)
    match = match_roster_identity(index, student_name=None, student_id="a 001")
    assert match.entry is not None
    assert match.match_kind == "id"


def test_confirm_roster_requires_entries(session) -> None:
    exam = _create_exam(session)
    with pytest.raises(RosterError):
        confirm_roster(session, exam.id)
    replace_roster_entries(
        session,
        exam.id,
        [ParsedRosterEntry("张三", "20240101")],
        source="manual",
    )
    session.commit()
    confirmed = confirm_roster(session, exam.id)
    assert confirmed.roster_status == "confirmed"
