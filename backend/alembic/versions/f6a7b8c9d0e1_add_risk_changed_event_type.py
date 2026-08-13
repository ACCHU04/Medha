"""add risk_changed event type value

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the risk_changed event type to the case_event_type enum."""
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TYPE case_event_type ADD VALUE IF NOT EXISTS 'risk_changed'"))


def downgrade() -> None:
    """Postgres cannot remove enum values; nothing to do."""
    pass
