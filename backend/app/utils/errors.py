from __future__ import annotations

SENSITIVE_ERROR_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer ",
    "token",
    "secret",
    "password",
    "traceback",
    "httpx",
    "openai",
    "paddle",
)


def public_error_message(exc: Exception, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    lowered = message.lower()
    if any(marker in lowered for marker in SENSITIVE_ERROR_MARKERS):
        return fallback
    if len(message) > 300:
        return fallback
    return message


def sanitized_error_summary(exc: Exception, fallback: str = "Processing failed") -> str:
    public_message = public_error_message(exc, fallback)
    if public_message == fallback:
        return fallback
    return public_message[:300]
