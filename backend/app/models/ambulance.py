import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import AmbulanceStatus
from .user import utcnow, uuid_pk


class Ambulance(Base):
    __tablename__ = "ambulances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_pk)
    vehicle_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=True
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[AmbulanceStatus] = mapped_column(
        Enum(AmbulanceStatus, name="ambulance_status", native_enum=True),
        nullable=False,
        default=AmbulanceStatus.available,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    hospital = relationship("Hospital", back_populates="ambulances")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    cases = relationship("EmergencyCase", back_populates="ambulance")
    gps_points = relationship("GpsPoint", back_populates="ambulance")

    __table_args__ = (
        Index("ix_ambulances_hospital_status", "hospital_id", "status"),
        Index("ix_ambulances_assigned_to", "assigned_to_id"),
    )
