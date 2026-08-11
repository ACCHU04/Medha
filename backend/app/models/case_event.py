import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import CaseEventType
from .user import utcnow, uuid_pk


class CaseEvent(Base):
    """Append-only timeline for a case; also the audit trail for sync conflicts."""

    __tablename__ = "case_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_pk)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emergency_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[CaseEventType] = mapped_column(
        Enum(CaseEventType, name="case_event_type", native_enum=True), nullable=False
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
    )
    hlc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    case = relationship("EmergencyCase", back_populates="events")

    __table_args__ = (Index("ix_case_events_case_hlc", "case_id", "hlc"),)
