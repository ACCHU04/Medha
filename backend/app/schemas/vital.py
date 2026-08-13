from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import VitalSource


class VitalCreate(BaseModel):
    id: UUID | None = None
    timestamp: datetime | None = None
    device_id: UUID | None = None
    hlc: str | None = None
    heart_rate: int | None = Field(default=None, ge=0, le=300)
    spo2: int | None = Field(default=None, ge=0, le=100)
    systolic_bp: int | None = Field(default=None, ge=20, le=300)
    diastolic_bp: int | None = Field(default=None, ge=10, le=200)
    temperature: float | None = Field(default=None, ge=30, le=45)
    respiratory_rate: int | None = Field(default=None, ge=0, le=100)
    source: VitalSource = VitalSource.simulated
    # Payload-only (no table column): feeds SIRS screening at ingress.
    suspected_infection: bool | None = None


class VitalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    timestamp: datetime
    heart_rate: int | None
    spo2: int | None
    systolic_bp: int | None
    diastolic_bp: int | None
    temperature: float | None
    respiratory_rate: int | None
    source: VitalSource
