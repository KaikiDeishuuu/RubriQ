from __future__ import annotations

from fastapi import APIRouter

from app.api.answers import router as answers_router
from app.api.files import router as files_router
from app.api.exams import router as exams_router
from app.api.submissions import router as submissions_router

api_router = APIRouter()
api_router.include_router(exams_router)
api_router.include_router(submissions_router)
api_router.include_router(answers_router)
api_router.include_router(files_router)
