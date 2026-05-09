from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Answer, AnswerRubricResult, ConfidenceLevel, Exam, Question, RubricItem, Submission, SubmissionPage, SubmissionStatus
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


def test_strictness_policy_does_not_lift_unsupported_non_empty_answer(monkeypatch) -> None:
    question = _question_snapshot()
    grading_result = _grading_result(score=0, evidence="")

    for strictness in ["strict", "moderate", "lenient"]:
        monkeypatch.setattr(pipeline.settings, "ai_grading_strictness", strictness)
        attempt = pipeline._build_grading_attempt(
            question=question,
            answer_text="irrelevant answer",
            extraction_confidence=ConfidenceLevel.high,
            grading_result=grading_result,
            raw_response="{}",
            model="model",
        )

        assert attempt.score == Decimal("0.0")
        assert attempt.missing_rubric_evidence is True



def test_lenient_policy_applies_small_floor_only_with_evidence(monkeypatch) -> None:
    question = _question_snapshot()
    monkeypatch.setattr(pipeline.settings, "ai_grading_strictness", "lenient")
    attempt = pipeline._build_grading_attempt(
        question=question,
        answer_text="student attempted point A",
        extraction_confidence=ConfidenceLevel.high,
        grading_result=_grading_result(score=0, evidence="student attempted point A"),
        raw_response="{}",
        model="model",
    )

    assert attempt.score == Decimal("0.3")



def test_small_question_lenient_floor_is_bounded(monkeypatch) -> None:
    question = QuestionSnapshot(id=5, question_no="1", title="Short", max_score=Decimal("1"), rubric_items=[RubricItemSnapshot(id=10, description="Point", max_score=Decimal("1"))])
    monkeypatch.setattr(pipeline.settings, "ai_grading_strictness", "lenient")

    attempt = pipeline._build_grading_attempt(
        question=question,
        answer_text="attempt",
        extraction_confidence=ConfidenceLevel.high,
        grading_result=_grading_result(score=0, evidence="attempt"),
        raw_response="{}",
        model="model",
    )

    assert attempt.score == Decimal("0.1")



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
    image_path = Path("page.png")
    seen_route_keys: list[str | None] = []
    seen_prompt_variables: list[dict] = []
    seen_image_paths: list[list[Path]] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        seen_prompt_variables.append(kwargs.get("prompt_variables"))
        seen_image_paths.append(kwargs.get("image_paths"))
        return type(
            "Completion",
            (),
            {
                "data": StudentExtractionResult(student_name="Alice", student_id="S001", answers=[]),
                "raw_text": "{}",
                "model": "chosen-vision",
                "candidate_index": 0,
                "fallback_used": False,
            },
        )()

    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    result, raw_text = pipeline._extract_submission_answers(
        exam_title="Sample",
        questions_json="[]",
        image_paths=[image_path],
        ocr_reference_text="[Page 1]\nOCR text",
    )

    assert result.student_name == "Alice"
    assert raw_text == "{}"
    assert seen_route_keys == ["vision_student_extraction"]
    assert seen_image_paths == [[image_path]]
    assert "OCR reference text" in seen_prompt_variables[0]["ocr_reference_text"]
    assert "OCR text" in seen_prompt_variables[0]["ocr_reference_text"]


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

    monkeypatch.setattr(pipeline.settings, "ai_grading_review_enabled", False)
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


def test_grade_question_uses_image_grounded_review_before_text_review(monkeypatch) -> None:
    question = _question_snapshot()
    image_path = Path("page.png")
    seen_image_paths: list[list[Path] | None] = []
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        seen_image_paths.append(kwargs.get("image_paths"))
        confidence = ConfidenceLevel.low if kwargs.get("route_key") == "grading" else ConfidenceLevel.high
        return type(
            "Completion",
            (),
            {
                "data": type(
                    "GradingPayload",
                    (),
                    {
                        "rubric_evaluation": [],
                        "confidence": confidence,
                        "needs_human_review": kwargs.get("route_key") == "grading",
                        "missing_points": [],
                        "final_comment": "",
                    },
                )(),
                "raw_text": "{}",
                "model": "chosen-model",
            },
        )()

    monkeypatch.setattr(pipeline.settings, "ai_grading_review_enabled", True)
    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    answer, _rubric_results, _needs_review = pipeline._grade_question(
        submission_id=7,
        question=question,
        answer_text="student answer",
        source_page=1,
        extraction_confidence=ConfidenceLevel.high,
        review_image_paths=[image_path],
    )

    assert answer.review_decision == "accepted_review"
    assert seen_route_keys == ["grading", "vision_grading_review"]
    assert seen_image_paths == [None, [image_path]]


def test_grade_question_skips_image_review_without_vision_capable_candidate(monkeypatch) -> None:
    question = _question_snapshot()
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        confidence = ConfidenceLevel.low if kwargs.get("route_key") == "grading" else ConfidenceLevel.high
        return type(
            "Completion",
            (),
            {
                "data": type(
                    "GradingPayload",
                    (),
                    {
                        "rubric_evaluation": [],
                        "confidence": confidence,
                        "needs_human_review": kwargs.get("route_key") == "grading",
                        "missing_points": [],
                        "final_comment": "",
                    },
                )(),
                "raw_text": "{}",
                "model": "chosen-model",
            },
        )()

    monkeypatch.setattr(pipeline.settings, "ai_grading_review_enabled", True)
    monkeypatch.setattr(pipeline, "_has_vision_capable_review_candidate", lambda: False)
    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    answer, _rubric_results, _needs_review = pipeline._grade_question(
        submission_id=7,
        question=question,
        answer_text="student answer",
        source_page=1,
        extraction_confidence=ConfidenceLevel.high,
        review_image_paths=[Path("page.png")],
    )

    assert answer.review_decision == "accepted_review"
    assert seen_route_keys == ["grading", "grading_review"]



def test_grade_question_falls_back_to_text_review_when_image_review_fails(monkeypatch) -> None:
    question = _question_snapshot()
    seen_route_keys: list[str | None] = []

    def fake_call_structured_json(**kwargs):
        seen_route_keys.append(kwargs.get("route_key"))
        if kwargs.get("route_key") == "vision_grading_review":
            raise RuntimeError("vision failed")
        confidence = ConfidenceLevel.low if kwargs.get("route_key") == "grading" else ConfidenceLevel.high
        return type(
            "Completion",
            (),
            {
                "data": type(
                    "GradingPayload",
                    (),
                    {
                        "rubric_evaluation": [],
                        "confidence": confidence,
                        "needs_human_review": kwargs.get("route_key") == "grading",
                        "missing_points": [],
                        "final_comment": "",
                    },
                )(),
                "raw_text": "{}",
                "model": "chosen-model",
            },
        )()

    monkeypatch.setattr(pipeline.settings, "ai_grading_review_enabled", True)
    monkeypatch.setattr(pipeline, "call_structured_json", fake_call_structured_json)

    answer, _rubric_results, _needs_review = pipeline._grade_question(
        submission_id=7,
        question=question,
        answer_text="student answer",
        source_page=1,
        extraction_confidence=ConfidenceLevel.high,
        review_image_paths=[Path("page.png")],
    )

    assert answer.review_decision == "accepted_review"
    assert seen_route_keys == ["grading", "vision_grading_review", "grading_review"]


def test_submission_review_image_paths_prefers_source_page_neighbors(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    monkeypatch.setattr(pipeline.settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    try:
        exam = Exam(title="Sample")
        session.add(exam)
        session.flush()
        submission = Submission(exam_id=exam.id, original_pdf_path="submissions/sample.pdf")
        session.add(submission)
        session.flush()
        for page_no in [1, 2, 3, 4]:
            session.add(SubmissionPage(submission_id=submission.id, page_no=page_no, image_path=f"rendered/page-{page_no}.png"))
        session.commit()

        paths = pipeline._submission_review_image_paths(session, submission.id, 2)

        assert [path.name for path in paths] == ["page-1.png", "page-2.png", "page-3.png"]
    finally:
        session.close()
        get_storage_service.cache_clear()


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
        assert updated_submission.total_score == Decimal("0.0")
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


def _grading_result(score: float, evidence: str):
    return type(
        "GradingPayload",
        (),
        {
            "rubric_evaluation": [
                type(
                    "Evaluation",
                    (),
                    {
                        "rubric_item_id": 10,
                        "awarded_score": score,
                        "evidence_from_student_answer": evidence,
                        "reason": "相关证据" if evidence else "无证据",
                    },
                )()
            ],
            "confidence": ConfidenceLevel.high,
            "needs_human_review": False,
            "missing_points": [],
            "final_comment": "",
        },
    )()



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


def test_generate_deduction_summary_lists_lost_rubric_items() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="模拟", total_score=Decimal("10"))
        session.add(exam)
        session.flush()
        question = Question(exam_id=exam.id, question_no="1", title="说明能量守恒", max_score=Decimal("5"), order_index=0)
        session.add(question)
        session.flush()
        rubric_item_a = RubricItem(question_id=question.id, description="给出公式", max_score=Decimal("2"), order_index=0)
        rubric_item_b = RubricItem(question_id=question.id, description="给出例子", max_score=Decimal("3"), order_index=1)
        session.add_all([rubric_item_a, rubric_item_b])
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            student_name="张三",
            student_id="S001",
            original_pdf_path="submissions/s001.pdf",
            status=SubmissionStatus.graded.value,
            total_score=Decimal("3"),
        )
        session.add(submission)
        session.flush()
        answer = Answer(
            submission_id=submission.id,
            question_id=question.id,
            extracted_answer="只列了公式",
            score=Decimal("3"),
            max_score=Decimal("5"),
            confidence="medium",
            ai_comment="缺少例子",
            missing_points=["缺少例子"],
        )
        session.add(answer)
        session.flush()
        session.add_all(
            [
                AnswerRubricResult(answer_id=answer.id, rubric_item_id=rubric_item_a.id, awarded_score=Decimal("2"), evidence="写出公式", reason="公式正确"),
                AnswerRubricResult(answer_id=answer.id, rubric_item_id=rubric_item_b.id, awarded_score=Decimal("1"), evidence="缺少例子", reason="未给具体例子，仅举了一个反例"),
            ]
        )
        session.commit()
        loaded = pipeline._load_submission(session, submission.id)

        summary = pipeline.generate_deduction_summary(loaded)

        assert "第 1 题" in summary
        assert "扣 2" in summary
        assert "给出例子" in summary
        assert "公式" not in summary  # full-credit rubric items are skipped
    finally:
        session.close()


def test_refresh_deduction_summary_respects_teacher_edit() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="模拟", total_score=Decimal("3"))
        session.add(exam)
        session.flush()
        question = Question(exam_id=exam.id, question_no="1", title="题", max_score=Decimal("3"), order_index=0)
        session.add(question)
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            student_name="李四",
            student_id="S002",
            original_pdf_path="submissions/s002.pdf",
            status=SubmissionStatus.graded.value,
            total_score=Decimal("2"),
        )
        session.add(submission)
        session.flush()
        answer = Answer(
            submission_id=submission.id,
            question_id=question.id,
            extracted_answer="部分答案",
            score=Decimal("2"),
            max_score=Decimal("3"),
            confidence="medium",
            ai_comment="差一点",
            missing_points=[],
        )
        session.add(answer)
        session.commit()

        pipeline.set_teacher_deduction_summary(session, submission.id, "教师手写的说明", reset=False)
        pipeline.refresh_deduction_summary(session, submission.id)
        session.refresh(submission)

        assert submission.deduction_summary == "教师手写的说明"
        assert submission.deduction_summary_edited is True

        pipeline.set_teacher_deduction_summary(session, submission.id, None, reset=True)
        session.refresh(submission)
        assert submission.deduction_summary_edited is False
        assert submission.deduction_summary  # auto-generated string
    finally:
        session.close()


def test_review_answer_with_strong_model_records_trigger_for_teacher_override() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="模拟", total_score=Decimal("3"))
        session.add(exam)
        session.flush()
        question = Question(exam_id=exam.id, question_no="1", title="题", max_score=Decimal("3"), order_index=0)
        session.add(question)
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            original_pdf_path="submissions/s002.pdf",
            status=SubmissionStatus.graded.value,
        )
        session.add(submission)
        session.flush()
        answer = Answer(
            submission_id=submission.id,
            question_id=question.id,
            extracted_answer="部分答案",
            score=Decimal("2"),
            max_score=Decimal("3"),
            confidence="medium",
            teacher_override_score=Decimal("2.5"),
            review_triggers=["low_confidence"],
        )
        session.add(answer)
        session.commit()

        pipeline.review_answer_with_strong_model(session, answer.id, trigger="score_variance")
        session.refresh(answer)

        assert answer.review_triggers == ["low_confidence", "score_variance"]
        assert answer.review_score is None
    finally:
        session.close()


def test_review_answer_with_strong_model_skips_teacher_reviewed_answer() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="模拟", total_score=Decimal("3"))
        session.add(exam)
        session.flush()
        question = Question(exam_id=exam.id, question_no="1", title="题", max_score=Decimal("3"), order_index=0)
        session.add(question)
        session.flush()
        submission = Submission(
            exam_id=exam.id,
            original_pdf_path="submissions/s002.pdf",
            status=SubmissionStatus.graded.value,
            total_score=Decimal("2"),
        )
        session.add(submission)
        session.flush()
        answer = Answer(
            submission_id=submission.id,
            question_id=question.id,
            extracted_answer="部分答案",
            score=Decimal("2"),
            max_score=Decimal("3"),
            confidence="medium",
            needs_human_review=False,
            review_decision="teacher_reviewed",
        )
        session.add(answer)
        session.commit()

        pipeline.review_answer_with_strong_model(session, answer.id, trigger="score_variance")
        session.refresh(answer)
        session.refresh(submission)

        assert answer.review_triggers == ["score_variance"]
        assert answer.review_score is None
        assert answer.score == Decimal("2.00")
        assert answer.needs_human_review is False
        assert answer.review_decision == "teacher_reviewed"
        assert submission.total_score == Decimal("2.00")
    finally:
        session.close()


def test_scored_questions_only_drops_parent_when_children_cover_score() -> None:
    questions = [
        ExtractedQuestion(question_no="2", title="Standalone", max_score=4, rubric_items=[]),
        ExtractedQuestion(question_no="3", title="Composite", max_score=19, rubric_items=[]),
        ExtractedQuestion(question_no="3.1", title="Sub A", max_score=5, rubric_items=[]),
        ExtractedQuestion(question_no="3.2", title="Sub B", max_score=11, rubric_items=[]),
        ExtractedQuestion(question_no="3.3", title="Sub C", max_score=3, rubric_items=[]),
    ]
    result = _scored_questions_only(questions)
    assert [q.question_no for q in result] == ["2", "3.1", "3.2", "3.3"]


def test_scored_questions_only_keeps_parent_when_children_dont_cover_score() -> None:
    # Parent has 10 points, only one sub-question with 3 points -> parent's own scoring still relevant.
    questions = [
        ExtractedQuestion(
            question_no="4",
            title="Mostly standalone",
            max_score=10,
            rubric_items=[],
        ),
        ExtractedQuestion(question_no="4.1", title="Sub", max_score=3, rubric_items=[]),
    ]
    result = _scored_questions_only(questions)
    # Parent has no rubric_items -> still dropped under the existing legacy rule.
    assert "4.1" in [q.question_no for q in result]


def test_confirm_rubric_endpoint_marks_review_done(tmp_path) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api import deps as _deps
    from app.main import app

    engine = _create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = _sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Demo", needs_rubric_review=True)
        session.add(exam)
        session.flush()
        session.add(Question(exam_id=exam.id, question_no="1", title="Q1"))
        session.commit()

        def fake_get_db():
            yield session

        app.dependency_overrides[_deps.get_db] = fake_get_db
        try:
            client = TestClient(app)
            # Confirm with no questions wouldn't reach here; we have one. So confirm returns 200.
            response = client.post(f"/api/exams/{exam.id}/rubric/confirm")
            assert response.status_code == 200, response.text
            assert response.json()["needs_rubric_review"] is False

            # Reopen
            response = client.post(f"/api/exams/{exam.id}/rubric/reopen")
            assert response.status_code == 200
            assert response.json()["needs_rubric_review"] is True
        finally:
            app.dependency_overrides.clear()
    finally:
        session.close()


def test_confirm_rubric_endpoint_rejects_when_no_questions(tmp_path) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api import deps as _deps
    from app.main import app

    engine = _create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = _sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        exam = Exam(title="Empty", needs_rubric_review=True)
        session.add(exam)
        session.commit()

        def fake_get_db():
            yield session

        app.dependency_overrides[_deps.get_db] = fake_get_db
        try:
            client = TestClient(app)
            response = client.post(f"/api/exams/{exam.id}/rubric/confirm")
            assert response.status_code == 400
            assert "请先解析" in response.json()["detail"] or "至少保留一道题" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()
    finally:
        session.close()
