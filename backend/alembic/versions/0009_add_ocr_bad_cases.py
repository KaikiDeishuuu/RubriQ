"""add ocr bad cases

Revision ID: 0009_add_ocr_bad_cases
Revises: 0008_question_no_unique
Create Date: 2026-05-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_add_ocr_bad_cases"
down_revision = "0008_question_no_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_bad_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_key", sa.String(length=50), nullable=False),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("submission_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_page_id", sa.Integer(), sa.ForeignKey("batch_pages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("image_storage_path", sa.String(length=1024), nullable=False),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("ocr_model", sa.String(length=255), nullable=False),
        sa.Column("ocr_raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("ocr_error_message", sa.Text(), nullable=True),
        sa.Column("trigger_reason", sa.String(length=50), nullable=False),
        sa.Column("trigger_source", sa.String(length=20), nullable=False),
        sa.Column("reporter_note", sa.Text(), nullable=True),
        sa.Column("ground_truth_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("redact_pii", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("image_hash", "route_key", name="uq_ocr_bad_cases_image_route"),
    )
    op.create_index("ix_ocr_bad_cases_status", "ocr_bad_cases", ["status"])
    op.create_index("ix_ocr_bad_cases_route_key", "ocr_bad_cases", ["route_key"])


def downgrade() -> None:
    op.drop_index("ix_ocr_bad_cases_route_key", table_name="ocr_bad_cases")
    op.drop_index("ix_ocr_bad_cases_status", table_name="ocr_bad_cases")
    op.drop_table("ocr_bad_cases")
