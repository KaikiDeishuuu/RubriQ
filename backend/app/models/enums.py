from __future__ import annotations

import enum


class SubmissionStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    graded = "graded"
    needs_review = "needs_review"
    failed = "failed"


class ConfidenceLevel(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
