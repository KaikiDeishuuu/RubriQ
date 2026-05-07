from app.core.config import settings


def test_ai_and_render_settings_exist() -> None:
    assert settings.render_dpi > 0
    assert settings.ai_request_timeout_seconds > 0
    assert settings.ai_max_retries >= 0
    assert settings.ai_retry_backoff_seconds >= 0
    assert 1 <= settings.ai_grading_concurrency <= 6
    assert 1 <= settings.ai_grading_global_concurrency <= 8
