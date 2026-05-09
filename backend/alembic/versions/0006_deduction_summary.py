"""submission deduction summary

Revision ID: 0006_deduction_summary
Revises: 0005_exam_roster
Create Date: 2026-05-09 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0006_deduction_summary"
down_revision = "0005_exam_roster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("deduction_summary", sa.Text(), nullable=True))
    op.add_column(
        "submissions",
        sa.Column(
            "deduction_summary_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("submissions", "deduction_summary_edited")
    op.drop_column("submissions", "deduction_summary")
