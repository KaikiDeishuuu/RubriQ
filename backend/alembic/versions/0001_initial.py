"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="teacher"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("total_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("needs_rubric_review", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "exam_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False, server_default="rubric_pdf"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parsed_json", sa.JSON(), nullable=True),
        sa.Column("raw_ai_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_no", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("max_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "rubric_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("max_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_name", sa.String(length=255), nullable=True),
        sa.Column("student_id", sa.String(length=255), nullable=True),
        sa.Column("original_pdf_path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="uploaded"),
        sa.Column("total_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("raw_extraction_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "submission_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("raw_ai_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("extracted_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("max_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("ai_comment", sa.Text(), nullable=True),
        sa.Column("missing_points", sa.JSON(), nullable=False),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("teacher_override_score", sa.Numeric(10, 2), nullable=True),
        sa.Column("teacher_comment", sa.Text(), nullable=True),
        sa.Column("raw_ai_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "answer_rubric_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("answer_id", sa.Integer(), sa.ForeignKey("answers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rubric_item_id", sa.Integer(), sa.ForeignKey("rubric_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("awarded_score", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("answer_rubric_results")
    op.drop_table("answers")
    op.drop_table("submission_pages")
    op.drop_table("submissions")
    op.drop_table("rubric_items")
    op.drop_table("questions")
    op.drop_table("exam_files")
    op.drop_table("exams")
    op.drop_table("users")
