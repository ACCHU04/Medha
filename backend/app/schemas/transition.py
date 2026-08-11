from uuid import UUID

from pydantic import BaseModel

from ..models.enums import CaseEventType, CaseSeverity
from .case import CaseOut
from .case_event import CaseEventOut


class TransitionCreate(BaseModel):
    event_type: CaseEventType
    severity: CaseSeverity | None = None
    note: str | None = None
    hospital_id: UUID | None = None


class TransitionOut(BaseModel):
    case: CaseOut
    event: CaseEventOut
