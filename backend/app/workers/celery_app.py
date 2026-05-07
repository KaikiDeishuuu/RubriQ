from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "quizocr_grader",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=600,
    task_time_limit=900,
)
