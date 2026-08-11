import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import VitalSource
from .user import utcnow, uuid_pk


class Vital(Base):
    __tablename__ = "vitals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_pk)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emergency_cases.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spo2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    systolic_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diastolic_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    respiratory_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[VitalSource] = mapped_column(
        Enum(VitalSource, name="vital_source", native_enum=True),
        nullable=False,
        default=VitalSource.simulated,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
    )
    hlc: Mapped[str | None] = mapped_column(String(64), nullable=True)

    case = relationship("EmergencyCase", back_populates="vitals")

    __table_args__ = (
        Index("ix_vitals_case_timestamp", "case_id", "timestamp"),
        Index("ix_vitals_device_id", "device_id"),
    )
