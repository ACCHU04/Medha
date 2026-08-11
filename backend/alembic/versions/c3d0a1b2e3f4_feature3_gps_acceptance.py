"""feature 3: gps points, hospital acceptance, user hospital link

Revision ID: c3d0a1b2e3f4
Revises: b2f1a9d3c4e5
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d0a1b2e3f4"
down_revision: Union[str, Sequence[str], None] = "b2f1a9d3c4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

case_acceptance = postgresql.ENUM(
    "accepted", "declined",
    name="case_acceptance", create_type=False,
)


def upgrade() -> None:
    """Upgrade schema: acceptance enum -> gps_points -> case/user additions."""
    case_acceptance.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "gps_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("ambulance_id", sa.Uuid(), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("hlc", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ambulance_id"], ["ambulances.id"],
            ondelete="RESTRICT", name="fk_gps_points_ambulance_id_ambulances",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["emergency_cases.id"],
            ondelete="RESTRICT", name="fk_gps_points_case_id_emergency_cases",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"],
            ondelete="RESTRICT", name="fk_gps_points_device_id_devices",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gps_points"),
    )
    op.create_index(
        "ix_gps_points_case_hlc", "gps_points", ["case_id", "hlc"], unique=False
    )
    op.create_index(
        "ix_gps_points_ambulance_id", "gps_points", ["ambulance_id"], unique=False
    )

    op.add_column(
        "users",
        sa.Column("hospital_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_users_hospital_id_hospitals"), "users", "hospitals",
        ["hospital_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_users_hospital_id", "users", ["hospital_id"], unique=False
    )

    op.add_column(
        "emergency_cases",
        sa.Column("acceptance_status", case_acceptance, nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("decision_by_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("decline_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("recommended_hospital_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "emergency_cases",
        sa.Column("preparation_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_emergency_cases_decision_by_id_users"), "emergency_cases", "users",
        ["decision_by_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_emergency_cases_recommended_hospital_id_hospitals"),
        "emergency_cases", "hospitals",
        ["recommended_hospital_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema: reverse of upgrade."""
    op.drop_constraint(
        op.f("fk_emergency_cases_recommended_hospital_id_hospitals"),
        "emergency_cases", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_emergency_cases_decision_by_id_users"),
        "emergency_cases", type_="foreignkey",
    )
    op.drop_column("emergency_cases", "preparation_notes")
    op.drop_column("emergency_cases", "prepared_at")
    op.drop_column("emergency_cases", "recommended_hospital_id")
    op.drop_column("emergency_cases", "decline_reason")
    op.drop_column("emergency_cases", "decision_at")
    op.drop_column("emergency_cases", "decision_by_id")
    op.drop_column("emergency_cases", "acceptance_status")

    op.drop_index("ix_users_hospital_id", table_name="users")
    op.drop_constraint(
        op.f("fk_users_hospital_id_hospitals"), "users", type_="foreignkey"
    )
    op.drop_column("users", "hospital_id")

    op.drop_index("ix_gps_points_ambulance_id", table_name="gps_points")
    op.drop_index("ix_gps_points_case_hlc", table_name="gps_points")
    op.drop_table("gps_points")

    case_acceptance.drop(op.get_bind(), checkfirst=True)
