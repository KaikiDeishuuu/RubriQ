# Celery Timeout Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make grading and batch AI-review Celery timeouts recover automatically once, then persist an explicit failed state instead of leaving submissions or batches stuck active.

**Architecture:** Add task-level soft-time-limit retry handling in `backend/app/workers/tasks.py`, with shared helpers that write final failure state for submissions and batch reviews. Add stale-state compensation in `backend/app/services/batch_pipeline.py` so hard kills or worker crashes that bypass Python handlers are finalized when batch status is refreshed or grading is started again. Keep existing manual retry semantics for failed submissions.

**Tech Stack:** Python, Celery, FastAPI, SQLAlchemy ORM, pytest, Docker Compose.

---

## File map

- Modify: `backend/app/core/config.py`
  - Add validated stale-timeout settings used by compensation logic.
- Modify: `docker-compose.yml`
  - Propagate the stale-timeout settings to backend and worker containers.
- Modify: `backend/app/workers/tasks.py`
  - Convert grading/review tasks to bound Celery tasks.
  - Catch `SoftTimeLimitExceeded`, retry once, and persist final failure state.
- Modify: `backend/app/services/batch_pipeline.py`
  - Add stale submission and stale batch-review finalization helpers.
  - Invoke compensation from `start_batch_grading()` and `refresh_batch_grading_status()` before queue/status decisions.
- Modify: `backend/app/api/submissions.py`
  - Reuse stale submission finalization for single-submission manual processing so active-but-stale rows can be restarted.
- Modify: `backend/tests/test_worker_tasks.py`
  - Add task-level soft-timeout retry/final-failure tests.
- Modify: `backend/tests/test_batch_pipeline.py`
  - Add hard-kill/stale-state compensation tests.
- Modify: `backend/tests/test_submissions_processing_api.py`
  - Add manual-processing stale-active restart test.

---

### Task 1: Add worker-task tests for submission timeout retry and final failure

**Files:**
- Modify: `backend/tests/test_worker_tasks.py`

- [ ] **Step 1: Add imports for Celery soft timeout and retry behavior**

Change the imports at the top of `backend/tests/test_worker_tasks.py` to:

```python
from __future__ import annotations

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import BatchStatus, BatchUploadMode, Exam, Submission, SubmissionBatch, SubmissionStatus
from app.workers import tasks
```

- [ ] **Step 2: Add a test that the first submission soft timeout retries without marking failed**

Append this test after `test_process_submission_task_skips_duplicate_active_message`:

```python
def test_process_submission_task_retries_once_on_soft_timeout(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
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
    submission_id = submission.id
    session.close()

    monkeypatch.setattr(tasks, "process_submission", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))

    with pytest.raises(Retry):
        tasks.process_submission_task.run(submission_id)

    check_session = session_factory()
    stored_submission = check_session.get(Submission, submission_id)
    assert stored_submission.status == SubmissionStatus.rendering.value
    assert stored_submission.error_message is None
    check_session.close()
```

- [ ] **Step 3: Add a test that the final submission soft timeout marks failed and refreshes batch status**

Append this test after the retry test:

```python
def test_process_submission_task_marks_failed_after_timeout_retry_is_exhausted(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    submission = Submission(
        exam_id=exam.id,
        batch_id=batch.id,
        original_pdf_path="submissions/sample.pdf",
        status=SubmissionStatus.processing.value,
        split_confirmed=True,
    )
    session.add(submission)
    session.commit()
    submission_id = submission.id
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "process_submission", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))
    monkeypatch.setattr(tasks.process_submission_task.request, "retries", 1, raising=False)

    with pytest.raises(SoftTimeLimitExceeded):
        tasks.process_submission_task.run(submission_id)

    check_session = session_factory()
    stored_submission = check_session.get(Submission, submission_id)
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_submission.status == SubmissionStatus.failed.value
    assert stored_submission.error_message == "Submission processing timed out"
    assert stored_batch.status == BatchStatus.completed_with_errors.value
    check_session.close()
```

- [ ] **Step 4: Run the new tests and verify they fail before implementation**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py::test_process_submission_task_retries_once_on_soft_timeout tests/test_worker_tasks.py::test_process_submission_task_marks_failed_after_timeout_retry_is_exhausted -q
```

Expected: FAIL because `process_submission_task` is not bound and does not catch `SoftTimeLimitExceeded` separately.

---

### Task 2: Implement submission soft-timeout retry and final failure state

**Files:**
- Modify: `backend/app/workers/tasks.py`
- Test: `backend/tests/test_worker_tasks.py`

- [ ] **Step 1: Import soft-timeout exception**

Change the top of `backend/app/workers/tasks.py` to:

```python
from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import update as sa_update
```

- [ ] **Step 2: Add task retry constants and helper functions**

Insert after the existing imports in `backend/app/workers/tasks.py`:

```python
SUBMISSION_TIMEOUT_MESSAGE = "Submission processing timed out"
BATCH_REVIEW_TIMEOUT_MESSAGE = "Batch grading review timed out"
TIMEOUT_RETRY_COUNTDOWN_SECONDS = 10


def _can_retry_task(task) -> bool:
    return task.request.retries < task.max_retries


def _mark_submission_failed(session, submission_id: int, message: str) -> None:
    submission = session.get(Submission, submission_id)
    if submission is None:
        return
    batch_id = submission.batch_id
    submission.status = SubmissionStatus.failed.value
    submission.error_message = message
    session.commit()
    if batch_id is not None:
        refresh_batch_grading_status(session, batch_id)
```

- [ ] **Step 3: Convert `process_submission_task` to a bound task with one retry**

Change the decorator and signature from:

```python
@celery_app.task(name="app.workers.tasks.process_submission_task")
def process_submission_task(submission_id: int) -> dict[str, int | str]:
```

to:

```python
@celery_app.task(name="app.workers.tasks.process_submission_task", bind=True, max_retries=1)
def process_submission_task(self, submission_id: int) -> dict[str, int | str]:
```

- [ ] **Step 4: Add explicit soft-timeout handling before the broad exception handler**

Replace the `except Exception as exc:` block in `process_submission_task` with:

```python
    except SoftTimeLimitExceeded:
        if _can_retry_task(self):
            session.rollback()
            raise self.retry(countdown=TIMEOUT_RETRY_COUNTDOWN_SECONDS)
        session.rollback()
        _mark_submission_failed(session, submission_id, SUBMISSION_TIMEOUT_MESSAGE)
        raise
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        session.rollback()
        submission = session.get(Submission, submission_id)
        if submission is not None:
            _mark_submission_failed(session, submission_id, sanitized_error_summary(exc, "Submission processing failed"))
        raise
```

- [ ] **Step 5: Run the submission worker timeout tests**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py::test_process_submission_task_retries_once_on_soft_timeout tests/test_worker_tasks.py::test_process_submission_task_marks_failed_after_timeout_retry_is_exhausted -q
```

Expected: PASS.

- [ ] **Step 6: Run the existing duplicate-message test**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py::test_process_submission_task_skips_duplicate_active_message -q
```

Expected: PASS.

---

### Task 3: Add worker-task tests for batch-review timeout retry and final failure

**Files:**
- Modify: `backend/tests/test_worker_tasks.py`

- [ ] **Step 1: Add a test that the first batch-review soft timeout retries without marking failed**

Append this test to `backend/tests/test_worker_tasks.py`:

```python
def test_review_batch_grading_task_retries_once_on_soft_timeout(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="queued",
    )
    session.add(batch)
    session.commit()
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "review_batch_grading", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))

    with pytest.raises(Retry):
        tasks.review_batch_grading_task.run(batch_id)

    check_session = session_factory()
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_batch.ai_review_status == "queued"
    assert stored_batch.ai_review_error_message is None
    assert stored_batch.status == BatchStatus.grading.value
    check_session.close()
```

- [ ] **Step 2: Add a test that the final batch-review soft timeout marks failed**

Append this test after the retry test:

```python
def test_review_batch_grading_task_marks_failed_after_timeout_retry_is_exhausted(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    session = session_factory()
    exam = Exam(title="Sample", roster_status="confirmed")
    session.add(exam)
    session.flush()
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="running",
    )
    session.add(batch)
    session.commit()
    batch_id = batch.id
    session.close()

    monkeypatch.setattr(tasks, "review_batch_grading", lambda *_args: (_ for _ in ()).throw(SoftTimeLimitExceeded()))
    monkeypatch.setattr(tasks.review_batch_grading_task.request, "retries", 1, raising=False)

    with pytest.raises(SoftTimeLimitExceeded):
        tasks.review_batch_grading_task.run(batch_id)

    check_session = session_factory()
    stored_batch = check_session.get(SubmissionBatch, batch_id)
    assert stored_batch.ai_review_status == "failed"
    assert stored_batch.ai_review_error_message == "Batch grading review timed out"
    assert stored_batch.status == BatchStatus.completed_with_errors.value
    check_session.close()
```

- [ ] **Step 3: Run the new batch-review worker tests and verify they fail before implementation**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py::test_review_batch_grading_task_retries_once_on_soft_timeout tests/test_worker_tasks.py::test_review_batch_grading_task_marks_failed_after_timeout_retry_is_exhausted -q
```

Expected: FAIL because `review_batch_grading_task` does not catch soft timeouts or retry.

---

### Task 4: Implement batch-review soft-timeout retry and final failure state

**Files:**
- Modify: `backend/app/workers/tasks.py`
- Test: `backend/tests/test_worker_tasks.py`

- [ ] **Step 1: Add a helper for final batch-review failure**

Insert this helper after `_mark_submission_failed()` in `backend/app/workers/tasks.py`:

```python
def _mark_batch_review_failed(session, batch_id: int, message: str) -> None:
    from app.models import BatchStatus, SubmissionBatch

    batch = session.get(SubmissionBatch, batch_id)
    if batch is None:
        return
    batch.ai_review_status = "failed"
    batch.ai_review_error_message = message
    batch.status = BatchStatus.completed_with_errors.value
    session.commit()
```

- [ ] **Step 2: Convert `review_batch_grading_task` to a bound task with one retry**

Change the decorator and signature from:

```python
@celery_app.task(name="app.workers.tasks.review_batch_grading_task", soft_time_limit=1800, time_limit=2400)
def review_batch_grading_task(batch_id: int) -> dict[str, int | str]:
```

to:

```python
@celery_app.task(name="app.workers.tasks.review_batch_grading_task", bind=True, max_retries=1, soft_time_limit=1800, time_limit=2400)
def review_batch_grading_task(self, batch_id: int) -> dict[str, int | str]:
```

- [ ] **Step 3: Add explicit soft-timeout and unexpected-error handling to batch review task**

Replace the body of `review_batch_grading_task` with:

```python
    session = SessionLocal()
    try:
        batch = review_batch_grading(session, batch_id)
        return {"batch_id": batch.id, "status": batch.status, "ai_review_status": batch.ai_review_status}
    except SoftTimeLimitExceeded:
        if _can_retry_task(self):
            session.rollback()
            raise self.retry(countdown=TIMEOUT_RETRY_COUNTDOWN_SECONDS)
        session.rollback()
        _mark_batch_review_failed(session, batch_id, BATCH_REVIEW_TIMEOUT_MESSAGE)
        raise
    except Exception as exc:  # noqa: BLE001 - worker must record unexpected failures
        session.rollback()
        _mark_batch_review_failed(session, batch_id, sanitized_error_summary(exc, "Batch grading review failed"))
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run all worker-task tests**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py -q
```

Expected: PASS.

---

### Task 5: Add config and compose settings for stale-state compensation

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add stale timeout settings to `Settings`**

In `backend/app/core/config.py`, add these fields after `ai_grading_batch_size`:

```python
    grading_stale_submission_seconds: int = Field(default=1200, alias="GRADING_STALE_SUBMISSION_SECONDS")
    grading_stale_batch_review_seconds: int = Field(default=3000, alias="GRADING_STALE_BATCH_REVIEW_SECONDS")
```

- [ ] **Step 2: Add validators for the new settings**

In `backend/app/core/config.py`, add these validators after `_validate_grading_batch_size`:

```python
    @field_validator("grading_stale_submission_seconds")
    @classmethod
    def _validate_grading_stale_submission_seconds(cls, value: int) -> int:
        if value < 600:
            raise ValueError("GRADING_STALE_SUBMISSION_SECONDS must be at least 600")
        return value

    @field_validator("grading_stale_batch_review_seconds")
    @classmethod
    def _validate_grading_stale_batch_review_seconds(cls, value: int) -> int:
        if value < 1800:
            raise ValueError("GRADING_STALE_BATCH_REVIEW_SECONDS must be at least 1800")
        return value
```

- [ ] **Step 3: Add stale timeout env vars to backend service**

In `docker-compose.yml`, add these under backend `environment` after `AI_GRADING_BATCH_SIZE`:

```yaml
      GRADING_STALE_SUBMISSION_SECONDS: ${GRADING_STALE_SUBMISSION_SECONDS:-1200}
      GRADING_STALE_BATCH_REVIEW_SECONDS: ${GRADING_STALE_BATCH_REVIEW_SECONDS:-3000}
```

- [ ] **Step 4: Add stale timeout env vars to worker service**

In `docker-compose.yml`, add the same lines under worker `environment` after `AI_GRADING_BATCH_SIZE`:

```yaml
      GRADING_STALE_SUBMISSION_SECONDS: ${GRADING_STALE_SUBMISSION_SECONDS:-1200}
      GRADING_STALE_BATCH_REVIEW_SECONDS: ${GRADING_STALE_BATCH_REVIEW_SECONDS:-3000}
```

- [ ] **Step 5: Run config import check**

Run:

```bash
cd backend && python3 -c "from app.core.config import Settings; s = Settings(); assert s.grading_stale_submission_seconds == 1200; assert s.grading_stale_batch_review_seconds == 3000"
```

Expected: command exits 0.

---

### Task 6: Add stale-state compensation tests for batch pipeline

**Files:**
- Modify: `backend/tests/test_batch_pipeline.py`

- [ ] **Step 1: Add datetime imports**

Change the top imports in `backend/tests/test_batch_pipeline.py` from:

```python
import zipfile
from pathlib import Path
```

to:

```python
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
```

- [ ] **Step 2: Add helper for stale timestamps**

Insert this helper above `_create_exam`:

```python
def _make_stale(row, seconds: int = 3600) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    row.updated_at = stale_at.replace(tzinfo=None)
```

- [ ] **Step 3: Add a test that refresh marks stale active submissions failed**

Append this test near the existing refresh status tests:

```python
def test_refresh_batch_grading_status_marks_stale_active_submission_failed(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_submission_seconds", 600)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    stale_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.grading.value)
    _make_stale(stale_submission)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    stored_submission = session.get(Submission, stale_submission.id)
    assert stored_submission.status == SubmissionStatus.failed.value
    assert stored_submission.error_message == "Submission processing timed out or worker stopped"
    assert updated_batch.status == BatchStatus.completed_with_errors.value
```

- [ ] **Step 4: Add a test that start grading can recover and requeue stale active submissions**

Append this test near `test_start_batch_grading_only_queues_uploaded_and_failed_submissions`:

```python
def test_start_batch_grading_requeues_stale_active_submission(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_submission_seconds", 600)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.ready_for_grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
    )
    session.add(batch)
    session.flush()
    stale_submission = _create_submission(session, exam.id, batch.id, SubmissionStatus.grading.value)
    _make_stale(stale_submission)
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.workers.tasks.process_submission_task.delay", queued_ids.append)

    updated_batch, queued_count = start_batch_grading(session, batch.id)

    assert queued_count == 1
    assert queued_ids == [stale_submission.id]
    assert updated_batch.status == BatchStatus.grading.value
    assert session.get(Submission, stale_submission.id).status == SubmissionStatus.processing.value
```

- [ ] **Step 5: Add a test that stale batch review is finalized as failed**

Append this test near `test_batch_review_failure_stores_sanitized_error`:

```python
def test_refresh_batch_grading_status_marks_stale_batch_review_failed(session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "ai_grading_review_enabled", True)
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_batch_review_seconds", 1800)
    exam = _create_exam(session)
    batch = SubmissionBatch(
        exam_id=exam.id,
        mode=BatchUploadMode.zip.value,
        status=BatchStatus.grading.value,
        source_filename="batch.zip",
        source_storage_path="batch.zip",
        ai_review_status="running",
    )
    session.add(batch)
    session.flush()
    _create_submission(session, exam.id, batch.id, SubmissionStatus.graded.value)
    _make_stale(batch, seconds=3600)
    session.commit()

    updated_batch = refresh_batch_grading_status(session, batch.id)

    stored_batch = session.get(SubmissionBatch, batch.id)
    assert stored_batch.ai_review_status == "failed"
    assert stored_batch.ai_review_error_message == "Batch grading review timed out or worker stopped"
    assert updated_batch.status == BatchStatus.completed_with_errors.value
```

- [ ] **Step 6: Run the stale batch-pipeline tests and verify they fail before implementation**

Run:

```bash
cd backend && pytest tests/test_batch_pipeline.py::test_refresh_batch_grading_status_marks_stale_active_submission_failed tests/test_batch_pipeline.py::test_start_batch_grading_requeues_stale_active_submission tests/test_batch_pipeline.py::test_refresh_batch_grading_status_marks_stale_batch_review_failed -q
```

Expected: FAIL because no stale-state compensation exists yet.

---

### Task 7: Implement stale-state compensation in batch pipeline

**Files:**
- Modify: `backend/app/services/batch_pipeline.py`
- Test: `backend/tests/test_batch_pipeline.py`

- [ ] **Step 1: Add datetime imports and messages**

Change imports at the top of `backend/app/services/batch_pipeline.py` from:

```python
import logging
import re
import time
import zipfile
```

to:

```python
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
```

Add these constants after `COMPLETED_SUBMISSION_STATUSES`:

```python
STALE_SUBMISSION_MESSAGE = "Submission processing timed out or worker stopped"
STALE_BATCH_REVIEW_MESSAGE = "Batch grading review timed out or worker stopped"
```

- [ ] **Step 2: Add stale cutoff helpers**

Insert after `load_batch_detail()`:

```python
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _stale_cutoff(seconds: int) -> datetime:
    return _as_naive_utc(_utc_now() - timedelta(seconds=seconds))
```

- [ ] **Step 3: Add stale active-submission finalizer**

Insert after `_stale_cutoff()`:

```python
def finalize_stale_active_submissions(session: Session, *, submission_id: int | None = None, batch_id: int | None = None) -> int:
    cutoff = _stale_cutoff(settings.grading_stale_submission_seconds)
    filters = [Submission.status.in_(ACTIVE_SUBMISSION_STATUSES), Submission.updated_at < cutoff]
    if submission_id is not None:
        filters.append(Submission.id == submission_id)
    if batch_id is not None:
        filters.append(Submission.batch_id == batch_id)
    updated = session.execute(
        sa_update(Submission)
        .where(*filters)
        .values(status=SubmissionStatus.failed.value, error_message=STALE_SUBMISSION_MESSAGE)
    ).rowcount
    if updated:
        session.commit()
    return updated
```

- [ ] **Step 4: Add stale batch-review finalizer**

Insert after `finalize_stale_active_submissions()`:

```python
def finalize_stale_batch_review(session: Session, batch_id: int) -> bool:
    cutoff = _stale_cutoff(settings.grading_stale_batch_review_seconds)
    updated = session.execute(
        sa_update(SubmissionBatch)
        .where(
            SubmissionBatch.id == batch_id,
            SubmissionBatch.ai_review_status.in_({"queued", "running"}),
            SubmissionBatch.updated_at < cutoff,
        )
        .values(
            ai_review_status="failed",
            ai_review_error_message=STALE_BATCH_REVIEW_MESSAGE,
            status=BatchStatus.completed_with_errors.value,
        )
    ).rowcount
    if updated:
        session.commit()
    return bool(updated)
```

- [ ] **Step 5: Invoke compensation before start-grading queue decisions**

Change the start of `start_batch_grading()` from:

```python
def start_batch_grading(session: Session, batch_id: int) -> tuple[SubmissionBatch, int]:
    batch = load_batch_detail(session, batch_id)
```

to:

```python
def start_batch_grading(session: Session, batch_id: int) -> tuple[SubmissionBatch, int]:
    finalize_stale_active_submissions(session, batch_id=batch_id)
    finalize_stale_batch_review(session, batch_id)
    batch = load_batch_detail(session, batch_id)
```

- [ ] **Step 6: Invoke compensation before refresh status decisions**

Change the start of `refresh_batch_grading_status()` from:

```python
def refresh_batch_grading_status(session: Session, batch_id: int) -> SubmissionBatch:
    batch = load_batch_detail(session, batch_id)
```

to:

```python
def refresh_batch_grading_status(session: Session, batch_id: int) -> SubmissionBatch:
    finalize_stale_active_submissions(session, batch_id=batch_id)
    finalize_stale_batch_review(session, batch_id)
    batch = load_batch_detail(session, batch_id)
```

- [ ] **Step 7: Prevent stale failed review from being overwritten to completed**

In `refresh_batch_grading_status()`, ensure the existing branch keeps this order exactly:

```python
            if any(submission.status == SubmissionStatus.failed.value for submission in submissions):
                next_status = BatchStatus.completed_with_errors.value
            elif all(submission.status in COMPLETED_SUBMISSION_STATUSES for submission in submissions):
                if _queue_batch_review_if_needed(session, batch):
                    next_status = BatchStatus.grading.value
                elif batch.ai_review_status == "failed":
                    next_status = BatchStatus.completed_with_errors.value
                elif batch.ai_review_status == "queued" or batch.ai_review_status == "running":
                    next_status = BatchStatus.grading.value
                else:
                    next_status = BatchStatus.completed.value
```

- [ ] **Step 8: Run the stale batch-pipeline tests**

Run:

```bash
cd backend && pytest tests/test_batch_pipeline.py::test_refresh_batch_grading_status_marks_stale_active_submission_failed tests/test_batch_pipeline.py::test_start_batch_grading_requeues_stale_active_submission tests/test_batch_pipeline.py::test_refresh_batch_grading_status_marks_stale_batch_review_failed -q
```

Expected: PASS.

---

### Task 8: Add API coverage for manually restarting stale active submissions

**Files:**
- Modify: `backend/tests/test_submissions_processing_api.py`
- Modify: `backend/app/api/submissions.py`

- [ ] **Step 1: Add datetime imports to API tests**

Change the top imports in `backend/tests/test_submissions_processing_api.py` from:

```python
from __future__ import annotations

import pytest
```

to:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
```

- [ ] **Step 2: Import batch pipeline settings for monkeypatching**

Change imports in `backend/tests/test_submissions_processing_api.py` from:

```python
from app.models import Answer, Exam, Question, Submission, SubmissionStatus
```

to:

```python
from app.models import Answer, Exam, Question, Submission, SubmissionStatus
from app.services import batch_pipeline
```

- [ ] **Step 3: Add a manual restart test for stale active submissions**

Append this test after `test_start_submission_processing_does_not_requeue_active_statuses`:

```python
def test_start_submission_processing_requeues_stale_active_status(client_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_pipeline.settings, "grading_stale_submission_seconds", 600)
    test_client, session = client_session
    submission = _create_submission(session, SubmissionStatus.grading.value)
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    submission.updated_at = stale_at.replace(tzinfo=None)
    session.commit()
    queued_ids: list[int] = []
    monkeypatch.setattr("app.api.submissions.process_submission_task.delay", queued_ids.append)

    response = test_client.post(f"/api/submissions/{submission.id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == SubmissionStatus.processing.value
    assert queued_ids == [submission.id]
    assert session.get(Submission, submission.id).error_message is None
```

- [ ] **Step 4: Run the new API test and verify it fails before implementation**

Run:

```bash
cd backend && pytest tests/test_submissions_processing_api.py::test_start_submission_processing_requeues_stale_active_status -q
```

Expected: FAIL because active submissions are returned without stale compensation.

- [ ] **Step 5: Reuse stale compensation in submission processing API**

In `backend/app/api/submissions.py`, add this import:

```python
from app.services.batch_pipeline import finalize_stale_active_submissions
```

Then change the start of `start_submission_processing()` from:

```python
    submission = _load_submission_or_404(session, submission_id)
```

to:

```python
    finalize_stale_active_submissions(session, submission_id=submission_id)
    submission = _load_submission_or_404(session, submission_id)
```

- [ ] **Step 6: Run API processing tests**

Run:

```bash
cd backend && pytest tests/test_submissions_processing_api.py::test_start_submission_processing_requeues_stale_active_status tests/test_submissions_processing_api.py::test_start_submission_processing_does_not_requeue_active_statuses tests/test_submissions_processing_api.py::test_start_submission_processing_queues_startable_statuses -q
```

Expected: PASS.

---

### Task 9: Run targeted and full backend verification

**Files:**
- Test: backend test suite

- [ ] **Step 1: Run worker-task tests**

Run:

```bash
cd backend && pytest tests/test_worker_tasks.py -q
```

Expected: PASS.

- [ ] **Step 2: Run batch-pipeline tests**

Run:

```bash
cd backend && pytest tests/test_batch_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 3: Run submission-processing API tests**

Run:

```bash
cd backend && pytest tests/test_submissions_processing_api.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full backend tests**

Run:

```bash
cd backend && pytest -q
```

Expected: PASS.

- [ ] **Step 5: Run Docker Compose config validation**

Run:

```bash
docker compose config >/tmp/quizocr-compose-config.yml
```

Expected: command exits 0.

---

### Task 10: Deploy locally and verify service health

**Files:**
- Runtime only

- [ ] **Step 1: Rebuild and restart backend and worker**

Run:

```bash
docker compose up -d --build backend worker
```

Expected: backend and worker containers rebuild and start successfully.

- [ ] **Step 2: Confirm containers are running**

Run:

```bash
docker compose ps backend worker postgres redis
```

Expected: `backend`, `worker`, `postgres`, and `redis` are running or healthy.

- [ ] **Step 3: Check backend import/config inside the container**

Run:

```bash
docker compose exec backend python3 -c "from app.core.config import settings; print(settings.grading_stale_submission_seconds, settings.grading_stale_batch_review_seconds)"
```

Expected output includes:

```text
1200 3000
```

- [ ] **Step 4: Inspect recent worker logs for startup errors**

Run:

```bash
docker compose logs --tail=120 worker
```

Expected: worker starts without import errors and lists tasks including `app.workers.tasks.process_submission_task` and `app.workers.tasks.review_batch_grading_task`.

- [ ] **Step 5: Inspect recent backend logs for startup errors**

Run:

```bash
docker compose logs --tail=120 backend
```

Expected: Alembic upgrade completes and Uvicorn starts without import or settings errors.

---

## Self-review notes

- Spec coverage: timeout retry once is covered in Tasks 1-4; hard-kill/worker-crash compensation is covered in Tasks 5-8; verification/deployment is covered in Tasks 9-10.
- Placeholder scan: no unresolved placeholder markers remain.
- Type consistency: status strings use existing `SubmissionStatus` and `BatchStatus`; stale logic uses existing `updated_at`; task retry tests call `.run()` on bound Celery tasks.
