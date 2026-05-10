from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin_token
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/check")
def check_token(_: None = Depends(require_admin_token)) -> dict[str, bool]:
    """Validate the bearer token. The dependency raises 401/403 on its own.

    The `auth_required` flag lets the frontend skip the login page when the
    backend is running without a token.
    """

    return {"ok": True, "auth_required": settings.admin_token_enforced}


@router.get("/status")
def auth_status() -> dict[str, bool]:
    """Public probe so the login page knows whether a token is required at all."""

    return {"auth_required": settings.admin_token_enforced}
