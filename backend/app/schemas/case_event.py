from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..models.enums import CaseEventType


class CaseEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    event_type: CaseEventType
    payload: dict | None
    device_id: UUID | None
    hlc: str | None
    created_at: datetime
