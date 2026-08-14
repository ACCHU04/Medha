"""feature: structured handover fields (GCS + medications)

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optional structured handover fields to emergency_cases.

    Both columns are nullable so existing cases and older clients keep
    working unchanged.
    """
    op.add_column("emergency_cases", sa.Column("gcs", sa.SmallInteger(), nullable=True))
    op.add_column("emergency_cases", sa.Column("medications", sa.Text(), nullable=True))


def downgrade() -> None:
    """Reverse schema: drop the two handover columns."""
    op.drop_column("emergency_cases", "medications")
    op.drop_column("emergency_cases", "gcs")
