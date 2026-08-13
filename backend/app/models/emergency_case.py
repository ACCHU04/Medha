import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import CaseAcceptance, CaseSeverity, CaseStatus
from .user import utcnow, uuid_pk


class EmergencyCase(Base):
    __tablename__ = "emergency_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_pk)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    ambulance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ambulances.id", ondelete="RESTRICT"), nullable=True
    )
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=True
    )
    acceptance_status: Mapped[CaseAcceptance | None] = mapped_column(
        Enum(CaseAcceptance, name="case_acceptance", native_enum=True),
        nullable=True,
    )
    decision_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=True
    )
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    preparation_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    route_geojson: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    severity: Mapped[CaseSeverity | None] = mapped_column(
        Enum(CaseSeverity, name="case_severity", native_enum=True), nullable=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", native_enum=True),
        nullable=False,
        default=CaseStatus.active,
    )
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
    )
    hlc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    patient = relationship("Patient", back_populates="cases")
    ambulance = relationship("Ambulance", back_populates="cases")
    hospital = relationship("Hospital", foreign_keys=[hospital_id])
    recommended_hospital = relationship(
        "Hospital", foreign_keys=[recommended_hospital_id]
    )
    decision_by = relationship(
        "User", foreign_keys=[decision_by_id]
    )
    created_by = relationship(
        "User", back_populates="created_cases", foreign_keys=[created_by_id]
    )
    vitals = relationship(
        "Vital",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Vital.timestamp",
    )
    events = relationship(
        "CaseEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="CaseEvent.created_at",
    )
    gps_points = relationship(
        "GpsPoint",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="GpsPoint.recorded_at",
    )
    ecg_tracings = relationship(
        "EcgTracing",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="EcgTracing.captured_at",
    )

    __table_args__ = (
        Index("ix_cases_patient_id", "patient_id"),
        Index("ix_cases_status", "status"),
        Index("ix_cases_created_at", "created_at"),
        Index("ix_cases_device_id", "device_id"),
    )
