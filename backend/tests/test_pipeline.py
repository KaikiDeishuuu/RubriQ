from app.schemas.ai import ExtractedQuestion, RubricParseResult
from app.services.pipeline import _scored_questions_only


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
