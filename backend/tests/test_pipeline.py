from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Answer, ConfidenceLevel, Exam, Question, Submission, SubmissionStatus
from app.schemas.ai import ExtractedQuestion, RubricParseResult, StudentExtractionResult
from app.services import pipeline
from app.services.pipeline import (
    QuestionSnapshot,
    RubricItemSnapshot,
    _build_empty_answer_fallback,
    _build_error_fallback,
    _build_grading_input,
    _recalculate_submission_total,
    _scored_questions_only,
    _strictness_instructions,
    process_submission,
)


def test_scored_questions_only_skips_unscored_parent_questions() -> None:
    questions = [
        ExtractedQuestion(question_no="1", title="Part 1", max_score=16, rubric_items=[]),
        ExtractedQuestion(question_no="1.1", title="Question 1.1", max_score=5, rubric_items=[]),
        ExtractedQuestion(question_no="1.2", title="Question 1.2", max_score=11, rubric_items=[]),
        ExtractedQuestion(question_no="2", title="Standalone", max_score=3, rubric_items=[]),
    ]

    scored_questions = _scored_questions_only(questions)

    assert [question.question_no for question in scored_questions] == ["1.1", "1.2", "2"]
    assert RubricParseResult(questions=scored_questions).questions == scored_questions


def test_build_grading_input_preserves_payload_shape() -> None:
    question = _question_snapshot()

    payload = _build_grading_input(question, "answer text")

    assert payload == {
        "question_no": "1.1",
        "question": "Explain the concept",
        "max_score": 5.0,
        "rubric_items": [
            {"id": 10, "description": "Point A", "max_score": 2.0},
            {"id": 11, "description": "Point B", "max_score": 3.0},
        ],
        "student_answer": "answer text",
    }


def test_strictness_instructions_returns_known_modes_and_empty_unknown() -> None:
    assert "Grade generously" in _strictness_instructions("lenient")
    assert "semantic equivalence" in _strictness_instructions("lenient")
    assert "Grade fairly" in _strictness_instructions("moderate")
    assert "Grade strictly" in _strictness_instructions("strict")
    assert _strictness_instructions("unknown") == ""


def test_empty_answer_fallback_marks_answer_for_review() -> None:
    question = _question_snapshot()

    answer, rubric_results, needs_review = _build_empty_answer_fallback(
        submission_id=7,
        question=question,
        source_page=None,
    )

    assert needs_review is True
    assert answer.submission_id == 7
    assert answer.question_id == question.id
    assert answer.score == Decimal("0")
    assert answer.confidence == ConfidenceLevel.low.value
    assert answer.needs_human_review is True
    assert answer.raw_ai_response == ""
    assert [result.awarded_score for result in rubric_results] == [Decimal("0"), Decimal("0")]


def test_error_fallback_preserves_error_response_and_review_flag() -> None:
    question = _question_snapshot()

    answer, rubric_results, needs_review = _build_error_fallback(
        submission_id=7,
        question=question,
        answer_text="student answer",
        source_page=2,
        extraction_confidence=ConfidenceLevel.high,
        raw_response="ERROR: provider failed",
    )

    assert needs_review is True
    assert answer.extracted_answer == "student answer"
    assert answer.source_page == 2
    assert answer.score == Decimal("0")
    assert answer.raw_ai_response == "ERROR: provider failed"
    assert answer.needs_human_review is True
    assert [result.reason for result in rubric_results] == [
        "AI 评分失败：provider failed",
        "AI 评分失败：provider failed",
    ]


def test_extract_submission_answers_uses_student_extraction_route(monkeypatch) -> None:
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        return type(
            "Completion",
            (),
            {
                "data": StudentExtractionResult(student_name="Alice", student_id="S001", answers=[]),
                "raw_text": "{}",
            },
        )()

    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    result, raw_text = pipeline._extract_submission_answers(
        exam_title="Sample",
        questions_json="[]",
        image_paths=[],
    )

    assert result.student_name == "Alice"
    assert raw_text == "{}"
    assert seen_route_keys == ["vision_student_extraction"]



def test_grade_question_uses_grading_route(monkeypatch) -> None:
    question = _question_snapshot()
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        return type(
            "Completion",
            (),
            {
                "data": type(
                    "GradingPayload",
                    (),
                    {
                        "rubric_evaluation": [],
                        "confidence": ConfidenceLevel.high,
                        "needs_human_review": False,
                        "missing_points": [],
                        "final_comment": "",
                    },
                )(),
                "raw_text": "{}",
                "model": "chosen-grader",
            },
        )()

    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    answer, _rubric_results, _needs_review = pipeline._grade_question(
        submission_id=7,
        question=question,
        answer_text="student answer",
        source_page=1,
        extraction_confidence=ConfidenceLevel.high,
    )

    assert answer.raw_ai_response == "{}"
    assert seen_route_keys == ["grading"]



def test_process_submission_without_questions_marks_needs_review(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Sample")
        session.add(exam)
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            original_pdf_path="submissions/sample.pdf",
            status=SubmissionStatus.processing.value,
        )
        session.add(submission)
        session.commit()
        monkeypatch.setattr(Path, "exists", lambda _path: True)
        monkeypatch.setattr(pipeline.get_storage_service(), "path_for", lambda _path: Path("sample.pdf"))
        monkeypatch.setattr(pipeline, "render_pdf_to_images", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(
            pipeline,
            "_extract_submission_answers",
            lambda **_kwargs: (StudentExtractionResult(student_name="Alice", student_id="S001", answers=[]), "{}"),
        )

        updated_submission = process_submission(session, submission.id)

        assert updated_submission.status == SubmissionStatus.needs_review.value
        assert updated_submission.total_score == Decimal("0.00")
        assert updated_submission.error_message == "No gradable questions were found for this submission"
    finally:
        session.close()



def test_recalculate_submission_total_uses_explicit_review_flags_only() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Sample")
        session.add(exam)
        session.flush()
        question = Question(exam_id=exam.id, question_no="1", title="Question 1", max_score=Decimal("5"))
        session.add(question)
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            original_pdf_path="submissions/sample.pdf",
            status=SubmissionStatus.needs_review.value,
        )
        session.add(submission)
        session.flush()
        session.add(
            Answer(
                submission_id=submission.id,
                question_id=question.id,
                extracted_answer="answer",
                score=Decimal("3"),
                max_score=Decimal("5"),
                confidence=ConfidenceLevel.low.value,
                needs_human_review=False,
            )
        )
        session.commit()

        _recalculate_submission_total(session, submission.id)

        session.refresh(submission)
        assert submission.total_score == Decimal("3.00")
        assert submission.status == SubmissionStatus.graded.value
    finally:
        session.close()



def _question_snapshot() -> QuestionSnapshot:
    return QuestionSnapshot(
        id=5,
        question_no="1.1",
        title="Explain the concept",
        max_score=Decimal("5"),
        rubric_items=[
            RubricItemSnapshot(id=10, description="Point A", max_score=Decimal("2")),
            RubricItemSnapshot(id=11, description="Point B", max_score=Decimal("3")),
        ],
    )
