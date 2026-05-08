from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Exam, Submission, SubmissionStatus
from app.workers import tasks


@pytest.fixture()
def session_factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(tasks, "SessionLocal", SessionLocal)
    return SessionLocal


def test_process_submission_task_skips_duplicate_active_message(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.rendering.value,
    )
    session.add(submission)
    session.commit()
    submission_id = submission.id
    session.close()
    called = False

    def fake_process_submission(_session, _submission_id):
        nonlocal called
        called = True

    monkeypatch.setattr(tasks, "process_submission", fake_process_submission)

    result = tasks.process_submission_task(submission_id)

    assert result == {"submission_id": submission_id, "status": SubmissionStatus.rendering.value}
    assert called is False
