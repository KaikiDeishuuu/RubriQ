"""exam roster

Revision ID: 0005_exam_roster
Revises: 0004_batch_candidate_excluded
Create Date: 2026-05-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0005_exam_roster"
down_revision = "0004_batch_candidate_excluded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exams",
        sa.Column(
            "roster_status",
            sa.String(length=50),
            nullable=False,
            server_default="not_uploaded",
        ),
    )
    op.add_column("exams", sa.Column("roster_raw_ai_response", sa.Text(), nullable=True))
    op.add_column("exams", sa.Column("roster_error_message", sa.Text(), nullable=True))

    op.create_table(
        "exam_roster_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "exam_id",
            sa.Integer(),
            sa.ForeignKey("exams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("student_name", sa.String(length=255), nullable=True),
        sa.Column("student_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("exam_id", "order_index", name="uq_roster_entries_exam_order"),
    )
    op.create_index("ix_roster_entries_exam_id", "exam_roster_entries", ["exam_id"])

    op.add_column(
        "batch_split_candidates",
        sa.Column("roster_entry_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_batch_candidates_roster_entry_id",
        "batch_split_candidates",
        "exam_roster_entries",
        ["roster_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_batch_candidates_roster_entry_id",
        "batch_split_candidates",
        ["roster_entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_batch_candidates_roster_entry_id", table_name="batch_split_candidates")
    op.drop_constraint(
        "fk_batch_candidates_roster_entry_id",
        "batch_split_candidates",
        type_="foreignkey",
    )
    op.drop_column("batch_split_candidates", "roster_entry_id")

    op.drop_index("ix_roster_entries_exam_id", table_name="exam_roster_entries")
    op.drop_table("exam_roster_entries")

    op.drop_column("exams", "roster_error_message")
    op.drop_column("exams", "roster_raw_ai_response")
    op.drop_column("exams", "roster_status")
