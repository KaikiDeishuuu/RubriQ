from __future__ import annotations

from collections.abc import Generator
import secrets

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.admin_token_enforced:
        return
    expected_token = (settings.admin_api_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API token is required but not configured",
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(token.strip(), expected_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin API token")
