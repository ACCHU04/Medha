"""add hospital event type values

Revision ID: d4e5f6a7b8c9
Revises: c3d0a1b2e3f4
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d0a1b2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ("hospital_accept", "hospital_decline", "hospital_prepare")


def upgrade() -> None:
    """Add hospital lifecycle event types to the case_event_type enum."""
    conn = op.get_bind()
    for value in _NEW_VALUES:
        conn.execute(sa.text(f"ALTER TYPE case_event_type ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    """Postgres cannot remove enum values; nothing to do."""
    pass
