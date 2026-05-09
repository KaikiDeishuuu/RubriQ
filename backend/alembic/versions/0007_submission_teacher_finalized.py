"""submission teacher finalized flag

Revision ID: 0007_teacher_finalized
Revises: 0006_deduction_summary
Create Date: 2026-05-09 15:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0007_teacher_finalized"
down_revision = "0006_deduction_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column(
            "teacher_finalized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("submissions", "teacher_finalized")
