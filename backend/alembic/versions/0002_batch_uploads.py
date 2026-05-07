"""batch uploads

Revision ID: 0002_batch_uploads
Revises: 0001_initial
Create Date: 2026-05-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_batch_uploads"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "submission_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="uploaded"),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_storage_path", sa.String(length=1024), nullable=False),
        sa.Column("pages_per_submission", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("split_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("raw_split_extraction_response", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_submission_batches_exam_id", "submission_batches", ["exam_id"])
    op.create_index("ix_submission_batches_status", "submission_batches", ["status"])

    op.create_table(
        "batch_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("submission_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("page_hash", sa.String(length=128), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("header_extraction_json", sa.JSON(), nullable=True),
        sa.Column("raw_ai_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("batch_id", "page_no", name="uq_batch_pages_batch_page_no"),
    )
    op.create_index("ix_batch_pages_batch_id", "batch_pages", ["batch_id"])

    op.create_table(
        "batch_split_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("submission_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.Column("student_name", sa.String(length=255), nullable=True),
        sa.Column("student_id", sa.String(length=255), nullable=True),
        sa.Column("split_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_storage_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("batch_id", "candidate_index", name="uq_batch_candidates_batch_index"),
    )
    op.create_index("ix_batch_split_candidates_batch_id", "batch_split_candidates", ["batch_id"])
    op.create_index("ix_batch_split_candidates_confirmed", "batch_split_candidates", ["confirmed"])

    op.add_column("submissions", sa.Column("batch_id", sa.Integer(), nullable=True))
    op.add_column("submissions", sa.Column("batch_candidate_id", sa.Integer(), nullable=True))
    op.add_column("submissions", sa.Column("source_mode", sa.String(length=50), nullable=True))
    op.add_column("submissions", sa.Column("split_confidence", sa.Float(), nullable=True))
    op.add_column(
        "submissions",
        sa.Column("split_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_foreign_key(
        "fk_submissions_batch_id",
        "submissions",
        "submission_batches",
        ["batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_submissions_batch_candidate_id",
        "submissions",
        "batch_split_candidates",
        ["batch_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_submissions_batch_candidate_id", "submissions", ["batch_candidate_id"])
    op.create_index("ix_submissions_batch_id", "submissions", ["batch_id"])

    op.add_column("submission_pages", sa.Column("page_hash", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("submission_pages", "page_hash")

    op.drop_index("ix_submissions_batch_id", table_name="submissions")
    op.drop_constraint("uq_submissions_batch_candidate_id", "submissions", type_="unique")
    op.drop_constraint("fk_submissions_batch_candidate_id", "submissions", type_="foreignkey")
    op.drop_constraint("fk_submissions_batch_id", "submissions", type_="foreignkey")
    op.drop_column("submissions", "split_confirmed")
    op.drop_column("submissions", "split_confidence")
    op.drop_column("submissions", "source_mode")
    op.drop_column("submissions", "batch_candidate_id")
    op.drop_column("submissions", "batch_id")

    op.drop_index("ix_batch_split_candidates_confirmed", table_name="batch_split_candidates")
    op.drop_index("ix_batch_split_candidates_batch_id", table_name="batch_split_candidates")
    op.drop_table("batch_split_candidates")
    op.drop_index("ix_batch_pages_batch_id", table_name="batch_pages")
    op.drop_table("batch_pages")
    op.drop_index("ix_submission_batches_status", table_name="submission_batches")
    op.drop_index("ix_submission_batches_exam_id", table_name="submission_batches")
    op.drop_table("submission_batches")
