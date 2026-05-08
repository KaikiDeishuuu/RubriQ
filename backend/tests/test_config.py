import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


def _settings(**overrides) -> Settings:
    defaults = {
        "AI_BASE_URL": "https://base.test/v1",
        "AI_API_KEY": "base-key",
        "AI_VISION_BASE_URL": "",
        "AI_VISION_API_KEY": "",
        "AI_GRADING_BASE_URL": "",
        "AI_GRADING_API_KEY": "",
        "AI_VISION_MODEL": "vision-default",
        "AI_GRADING_MODEL": "grading-default",
        "AI_VISION_CHAIN": None,
        "AI_VISION_RUBRIC_CHAIN": None,
        "AI_VISION_STUDENT_EXTRACTION_CHAIN": None,
        "AI_VISION_SPLIT_HEADER_CHAIN": None,
        "AI_GRADING_CHAIN": None,
        "AI_GRADING_REVIEW_MODEL": None,
        "AI_GRADING_REVIEW_CHAIN": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_ai_and_render_settings_exist() -> None:
    assert settings.render_dpi > 0
    assert settings.ai_request_timeout_seconds > 0
    assert settings.ai_max_retries >= 0
    assert settings.ai_retry_backoff_seconds >= 0
    assert 1 <= settings.ai_grading_concurrency <= 6
    assert 1 <= settings.ai_grading_global_concurrency <= 8



def test_ai_model_candidates_fall_back_to_legacy_single_model() -> None:
    app_settings = _settings()

    vision_candidates = app_settings.ai_model_candidates("vision_student_extraction")
    grading_candidates = app_settings.ai_model_candidates("grading")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key) for candidate in vision_candidates] == [
        ("vision", "vision-default", "https://base.test/v1", "base-key")
    ]
    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key) for candidate in grading_candidates] == [
        ("grading", "grading-default", "https://base.test/v1", "base-key")
    ]



def test_ai_model_candidates_prefer_task_chain_over_generic_chain() -> None:
    app_settings = _settings(
        AI_VISION_BASE_URL="https://vision.test/v1",
        AI_VISION_API_KEY="vision-key",
        AI_VISION_CHAIN='[{"model":"generic-vision"}]',
        AI_VISION_STUDENT_EXTRACTION_CHAIN=(
            '[{"model":"gemini-ocr","base_url":"https://gemini.test/v1","api_key":"gemini-key"},'
            '{"model":"vision-backup"}]'
        ),
    )

    candidates = app_settings.ai_model_candidates("vision_student_extraction")
    rubric_candidates = app_settings.ai_model_candidates("vision_rubric")

    assert [(candidate.model, candidate.base_url, candidate.api_key) for candidate in candidates] == [
        ("gemini-ocr", "https://gemini.test/v1", "gemini-key"),
        ("vision-backup", "https://vision.test/v1", "vision-key"),
    ]
    assert [candidate.model for candidate in rubric_candidates] == ["generic-vision"]



def test_ai_model_candidates_parse_grading_chain() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_CHAIN='[{"model":"grader-fast"},{"model":"grader-safe","api_key":"safe-key"}]',
    )

    candidates = app_settings.ai_model_candidates("grading")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key) for candidate in candidates] == [
        ("grading", "grader-fast", "https://grading.test/v1", "grading-key"),
        ("grading", "grader-safe", "https://grading.test/v1", "safe-key"),
    ]



def test_ai_model_candidates_reject_invalid_chain() -> None:
    app_settings = _settings(AI_VISION_CHAIN="not-json")

    with pytest.raises(ValueError, match="JSON arrays"):
        app_settings.ai_model_candidates("vision_rubric")


def test_ai_model_candidates_use_review_model_for_grading_review_route() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_REVIEW_MODEL="grader-strong",
    )

    candidates = app_settings.ai_model_candidates("grading_review")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key) for candidate in candidates] == [
        ("grading", "grader-strong", "https://grading.test/v1", "grading-key")
    ]


def test_ai_model_candidates_parse_review_chain() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_REVIEW_CHAIN=(
            '[{"model":"grader-strong","base_url":"https://review.test/v1","api_key":"review-key"},'
            '{"model":"grader-backup"}]'
        ),
    )

    candidates = app_settings.ai_model_candidates("grading_review")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key) for candidate in candidates] == [
        ("grading", "grader-strong", "https://review.test/v1", "review-key"),
        ("grading", "grader-backup", "https://grading.test/v1", "grading-key"),
    ]


def test_invalid_review_thresholds_are_rejected() -> None:
    with pytest.raises(ValidationError, match="AI grading review ratios"):
        _settings(AI_GRADING_REVIEW_SCORE_DELTA_RATIO=1.5)
    with pytest.raises(ValidationError, match="AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS"):
        _settings(AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS=1)


def test_invalid_grading_strictness_is_rejected() -> None:
    with pytest.raises(ValidationError, match="AI_GRADING_STRICTNESS"):
        Settings(AI_GRADING_STRICTNESS="random")
