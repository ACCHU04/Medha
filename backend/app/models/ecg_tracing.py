import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .user import utcnow


class EcgTracing(Base):
    """Digitized paper ECG (Feature 4).

    The ambulance device captures a paper ECG photo, digitizes it in the
    browser (quality check -> crop -> grid detection -> composite trace) and
    rides the offline sync outbox to get here. Images are stored as compressed
    bytes (BYTEA); the waveform + quality metrics ride in JSONB. This is a
    transportable record only — it performs no diagnostic interpretation.
    """

    __tablename__ = "ecg_tracings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emergency_cases.id", ondelete="RESTRICT")
    )
    captured_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="paper_photo")
    lead_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paper_speed: Mapped[str] = mapped_column(String(8), nullable=False, default="25")
    image_original: Mapped[bytes] = mapped_column(nullable=False)
    image_normalized: Mapped[bytes | None] = mapped_column(nullable=True)
    waveform: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    hlc: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    case = relationship("EmergencyCase", back_populates="ecg_tracings")
    captured_by = relationship("User")

    __table_args__ = (
        Index("ix_ecg_tracings_case_id", "case_id"),
        Index("ix_ecg_tracings_captured_at", "captured_at"),
    )
