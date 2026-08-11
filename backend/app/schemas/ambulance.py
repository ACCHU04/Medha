from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..models.enums import AmbulanceStatus


class AmbulanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehicle_number: str
    hospital_id: UUID | None
    assigned_to_id: UUID | None
    status: AmbulanceStatus
    created_at: datetime
