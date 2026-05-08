from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Exam, ExamFile, Submission
from app.api import exams as exams_api
from app.api import submissions as submissions_api


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_delete_submission_does_not_delete_storage_when_commit_fails(session, monkeypatch: pytest.MonkeyPatch) -> None:
    submission = _create_submission(session)
    storage = RecordingStorage()
    monkeypatch.setattr(submissions_api, "get_storage_service", lambda: storage)
    monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))

    with pytest.raises(RuntimeError, match="commit failed"):
        submissions_api.delete_submission(submission.id, session)

    assert storage.deleted_files == []
    assert storage.deleted_trees == []


def test_delete_submission_deletes_storage_after_successful_commit(session, monkeypatch: pytest.MonkeyPatch) -> None:
    submission = _create_submission(session)
    storage = RecordingStorage(raise_on_delete=True)
    monkeypatch.setattr(submissions_api, "get_storage_service", lambda: storage)

    response = submissions_api.delete_submission(submission.id, session)

    assert response == {"message": f"Submission {submission.id} deleted"}
    assert storage.deleted_files == ["submissions/sample.pdf"]
    assert storage.deleted_trees == [f"rendered/submissions/{submission.id}"]


def test_delete_exam_does_not_delete_storage_when_commit_fails(session, monkeypatch: pytest.MonkeyPatch) -> None:
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    session.add(ExamFile(exam_id=exam.id, file_type="rubric_pdf", original_filename="rubric.pdf", storage_path="rubric.pdf"))
    session.commit()
    storage = RecordingStorage()
    monkeypatch.setattr(exams_api, "get_storage_service", lambda: storage)
    monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))

    with pytest.raises(RuntimeError, match="commit failed"):
        exams_api.delete_exam(exam.id, session)

    assert storage.deleted_files == []
    assert storage.deleted_trees == []


class RecordingStorage:
    def __init__(self, *, raise_on_delete: bool = False) -> None:
        self.raise_on_delete = raise_on_delete
        self.deleted_files: list[str] = []
        self.deleted_trees: list[str] = []

    def delete(self, path: str) -> None:
        self.deleted_files.append(path)
        if self.raise_on_delete:
            raise RuntimeError("storage delete failed")

    def delete_tree(self, path: str) -> None:
        self.deleted_trees.append(path)
        if self.raise_on_delete:
            raise RuntimeError("storage tree delete failed")


def _create_submission(session) -> Submission:
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    submission = Submission(exam_id=exam.id, original_pdf_path="submissions/sample.pdf")
    session.add(submission)
    session.commit()
    return submission
