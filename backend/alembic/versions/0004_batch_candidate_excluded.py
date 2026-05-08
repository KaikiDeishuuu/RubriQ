"""batch candidate excluded flag

Revision ID: 0004_batch_candidate_excluded
Revises: 0003_ai_grading_review
Create Date: 2026-05-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0004_batch_candidate_excluded"
down_revision = "0003_ai_grading_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_split_candidates",
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("batch_split_candidates", "excluded")
