import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class GpsPoint(Base):
    """Append-only GPS fix reported by an ambulance device (Feature 3).

    Rides the offline sync outbox like vitals; the ETA feature consumes the
    newest fix per case. Immutable once written.
    """

    __tablename__ = "gps_points"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emergency_cases.id", ondelete="CASCADE"), index=True
    )
    ambulance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ambulances.id"), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    hlc: Mapped[str | None] = mapped_column(nullable=True)

    case: Mapped["EmergencyCase"] = relationship(back_populates="gps_points")  # noqa: F821
    ambulance: Mapped["Ambulance"] = relationship(back_populates="gps_points")  # noqa: F821

    __table_args__ = (
        Index("ix_gps_points_case_recorded", "case_id", "recorded_at", "hlc"),
    )
