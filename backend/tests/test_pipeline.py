from decimal import Decimal

from app.models import ConfidenceLevel
from app.schemas.ai import ExtractedQuestion, RubricParseResult
from app.services.pipeline import (
    QuestionSnapshot,
    RubricItemSnapshot,
    _build_empty_answer_fallback,
    _build_error_fallback,
    _build_grading_input,
    _scored_questions_only,
    _strictness_instructions,
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
