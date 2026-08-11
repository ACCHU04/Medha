"""initial schema

Revision ID: 91cd1267d0fe
Revises:
Create Date: 2026-08-11 01:54:18.241635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "91cd1267d0fe"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Native PostgreSQL enum types. Lifecycle is managed explicitly so that
# `downgrade` removes the schema cleanly (no orphaned enum types).
user_role = postgresql.ENUM(
    "paramedic", "doctor", "hospital_admin", name="user_role", create_type=False
)
ambulance_status = postgresql.ENUM(
    "available", "en_route", "transporting", "offline",
    name="ambulance_status", create_type=False,
)
case_severity = postgresql.ENUM(
    "low", "moderate", "high", "critical", name="case_severity", create_type=False
)
case_status = postgresql.ENUM(
    "active", "transporting", "at_hospital", "closed",
    name="case_status", create_type=False,
)
vital_source = postgresql.ENUM(
    "device", "simulated", "manual", name="vital_source", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    user_role.create(op.get_bind(), checkfirst=True)
    ambulance_status.create(op.get_bind(), checkfirst=True)
    case_severity.create(op.get_bind(), checkfirst=True)
    case_status.create(op.get_bind(), checkfirst=True)
    vital_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "hospitals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_hospitals"),
    )
    op.create_index("ix_hospitals_city", "hospitals", ["city"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "ambulances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("vehicle_number", sa.String(length=64), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=True),
        sa.Column("status", ambulance_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"],
            ondelete="RESTRICT", name="fk_ambulances_hospital_id_hospitals",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ambulances"),
        sa.UniqueConstraint("vehicle_number", name="uq_ambulances_vehicle_number"),
    )
    op.create_index(
        "ix_ambulances_hospital_status", "ambulances", ["hospital_id", "status"], unique=False
    )

    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(length=16), nullable=True),
        sa.Column("blood_type", sa.String(length=8), nullable=True),
        sa.Column("medical_history", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_patients_created_by_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_patients"),
    )
    op.create_index("ix_patients_created_by", "patients", ["created_by_id"], unique=False)

    op.create_table(
        "emergency_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("ambulance_id", sa.Uuid(), nullable=True),
        sa.Column("hospital_id", sa.Uuid(), nullable=True),
        sa.Column("severity", case_severity, nullable=True),
        sa.Column("status", case_status, nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ambulance_id"], ["ambulances.id"],
            ondelete="RESTRICT", name="fk_emergency_cases_ambulance_id_ambulances",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_emergency_cases_created_by_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"],
            ondelete="RESTRICT", name="fk_emergency_cases_hospital_id_hospitals",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"],
            ondelete="RESTRICT", name="fk_emergency_cases_patient_id_patients",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_emergency_cases"),
    )
    op.create_index("ix_cases_created_at", "emergency_cases", ["created_at"], unique=False)
    op.create_index("ix_cases_patient_id", "emergency_cases", ["patient_id"], unique=False)
    op.create_index("ix_cases_status", "emergency_cases", ["status"], unique=False)

    op.create_table(
        "vitals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heart_rate", sa.Integer(), nullable=True),
        sa.Column("spo2", sa.Integer(), nullable=True),
        sa.Column("systolic_bp", sa.Integer(), nullable=True),
        sa.Column("diastolic_bp", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("respiratory_rate", sa.Integer(), nullable=True),
        sa.Column("source", vital_source, nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["emergency_cases.id"],
            ondelete="CASCADE", name="fk_vitals_case_id_emergency_cases",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vitals"),
    )
    op.create_index("ix_vitals_case_timestamp", "vitals", ["case_id", "timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_vitals_case_timestamp", table_name="vitals")
    op.drop_table("vitals")
    op.drop_index("ix_cases_status", table_name="emergency_cases")
    op.drop_index("ix_cases_patient_id", table_name="emergency_cases")
    op.drop_index("ix_cases_created_at", table_name="emergency_cases")
    op.drop_table("emergency_cases")
    op.drop_index("ix_patients_created_by", table_name="patients")
    op.drop_table("patients")
    op.drop_index("ix_ambulances_hospital_status", table_name="ambulances")
    op.drop_table("ambulances")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_table("users")
    op.drop_index("ix_hospitals_city", table_name="hospitals")
    op.drop_table("hospitals")

    vital_source.drop(op.get_bind(), checkfirst=True)
    case_status.drop(op.get_bind(), checkfirst=True)
    case_severity.drop(op.get_bind(), checkfirst=True)
    ambulance_status.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
