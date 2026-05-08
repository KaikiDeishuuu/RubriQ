from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.db.base import Base
from app.main import app
from app.models import Answer, ConfidenceLevel, Exam, Question, Submission, SubmissionStatus


@pytest.fixture()
def client_session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    def fake_get_db():
        yield session

    app.dependency_overrides[deps.get_db] = fake_get_db
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_mark_answer_reviewed_preserves_existing_override(client_session) -> None:
    test_client, session = client_session
    submission, answers = _create_submission_with_answers(session)
    reviewed_answer = answers[0]

    response = test_client.put(f"/api/answers/{reviewed_answer.id}/override", json={"reviewed": True})

    assert response.status_code == 200
    assert response.json()["needs_human_review"] is False
    session.refresh(submission)
    session.refresh(reviewed_answer)
    assert submission.status == SubmissionStatus.graded.value
    assert submission.total_score == Decimal("7.00")
    assert reviewed_answer.teacher_override_score == Decimal("4.00")
    assert reviewed_answer.teacher_comment == "checked"


def test_mark_answer_needs_review_updates_submission_status(client_session) -> None:
    test_client, session = client_session
    submission, answers = _create_submission_with_answers(session, first_needs_review=False)
    answer = answers[1]

    response = test_client.put(f"/api/answers/{answer.id}/override", json={"reviewed": False})

    assert response.status_code == 200
    assert response.json()["needs_human_review"] is True
    session.refresh(submission)
    assert submission.status == SubmissionStatus.needs_review.value


def test_override_score_without_reviewed_keeps_review_flag(client_session) -> None:
    test_client, session = client_session
    submission, answers = _create_submission_with_answers(session)
    answer = answers[0]

    response = test_client.put(
        f"/api/answers/{answer.id}/override",
        json={"teacher_override_score": 4.5, "teacher_comment": "manual score"},
    )

    assert response.status_code == 200
    assert response.json()["needs_human_review"] is True
    session.refresh(submission)
    session.refresh(answer)
    assert submission.status == SubmissionStatus.needs_review.value
    assert submission.total_score == Decimal("7.50")
    assert answer.teacher_override_score == Decimal("4.50")
    assert answer.teacher_comment == "manual score"


def _create_submission_with_answers(session, *, first_needs_review: bool = True) -> tuple[Submission, list[Answer]]:
    exam = Exam(title="Sample")
    session.add(exam)
    session.flush()
    questions = [
        Question(exam_id=exam.id, question_no="1", title="Question 1", max_score=Decimal("5"), order_index=1),
        Question(exam_id=exam.id, question_no="2", title="Question 2", max_score=Decimal("5"), order_index=2),
    ]
    session.add_all(questions)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.needs_review.value if first_needs_review else SubmissionStatus.graded.value,
        total_score=Decimal("5"),
    )
    session.add(submission)
    session.flush()
    answers = [
        Answer(
            submission_id=submission.id,
            question_id=questions[0].id,
            extracted_answer="answer 1",
            score=Decimal("2"),
            max_score=Decimal("5"),
            confidence=ConfidenceLevel.low.value,
            needs_human_review=first_needs_review,
            teacher_override_score=Decimal("4"),
            teacher_comment="checked",
        ),
        Answer(
            submission_id=submission.id,
            question_id=questions[1].id,
            extracted_answer="answer 2",
            score=Decimal("3"),
            max_score=Decimal("5"),
            confidence=ConfidenceLevel.high.value,
            needs_human_review=False,
        ),
    ]
    session.add_all(answers)
    session.commit()
    return submission, answers
