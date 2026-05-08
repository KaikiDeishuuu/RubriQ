"""ai grading review

Revision ID: 0003_ai_grading_review
Revises: 0002_batch_uploads
Create Date: 2026-05-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_ai_grading_review"
down_revision = "0002_batch_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_batches",
        sa.Column("ai_review_status", sa.String(length=50), nullable=False, server_default="not_started"),
    )
    op.add_column("submission_batches", sa.Column("ai_review_error_message", sa.Text(), nullable=True))

    op.add_column("answers", sa.Column("fast_score", sa.Numeric(10, 2), nullable=True))
    op.add_column("answers", sa.Column("fast_confidence", sa.String(length=16), nullable=True))
    op.add_column("answers", sa.Column("fast_ai_comment", sa.Text(), nullable=True))
    op.add_column("answers", sa.Column("fast_missing_points", sa.JSON(), nullable=True))
    op.add_column("answers", sa.Column("fast_raw_ai_response", sa.Text(), nullable=True))
    op.add_column("answers", sa.Column("review_score", sa.Numeric(10, 2), nullable=True))
    op.add_column("answers", sa.Column("review_confidence", sa.String(length=16), nullable=True))
    op.add_column("answers", sa.Column("review_ai_comment", sa.Text(), nullable=True))
    op.add_column("answers", sa.Column("review_missing_points", sa.JSON(), nullable=True))
    op.add_column("answers", sa.Column("review_raw_ai_response", sa.Text(), nullable=True))
    op.add_column("answers", sa.Column("review_triggers", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("answers", sa.Column("review_decision", sa.String(length=50), nullable=False, server_default="not_required"))
    op.add_column("answers", sa.Column("review_model", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("answers", "review_model")
    op.drop_column("answers", "review_decision")
    op.drop_column("answers", "review_triggers")
    op.drop_column("answers", "review_raw_ai_response")
    op.drop_column("answers", "review_missing_points")
    op.drop_column("answers", "review_ai_comment")
    op.drop_column("answers", "review_confidence")
    op.drop_column("answers", "review_score")
    op.drop_column("answers", "fast_raw_ai_response")
    op.drop_column("answers", "fast_missing_points")
    op.drop_column("answers", "fast_ai_comment")
    op.drop_column("answers", "fast_confidence")
    op.drop_column("answers", "fast_score")

    op.drop_column("submission_batches", "ai_review_error_message")
    op.drop_column("submission_batches", "ai_review_status")
