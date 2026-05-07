from __future__ import annotations

import enum


class SubmissionStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    rendering = "rendering"
    extracting = "extracting"
    grading = "grading"
    graded = "graded"
    needs_review = "needs_review"
    failed = "failed"


class BatchUploadMode(str, enum.Enum):
    zip = "zip"
    combined_fixed = "combined_fixed"
    combined_auto = "combined_auto"


class BatchStatus(str, enum.Enum):
    uploaded = "uploaded"
    splitting = "splitting"
    needs_split_review = "needs_split_review"
    split_ready = "split_ready"
    materializing = "materializing"
    ready_for_grading = "ready_for_grading"
    grading = "grading"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


class ConfidenceLevel(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
