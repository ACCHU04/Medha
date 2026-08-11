from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GpsCreate(BaseModel):
    case_id: UUID
    ambulance_id: UUID
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    recorded_at: datetime | None = None


class GpsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    ambulance_id: UUID
    latitude: float
    longitude: float
    recorded_at: datetime
