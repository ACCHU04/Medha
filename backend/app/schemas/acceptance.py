from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AcceptRequest(BaseModel):
    hospital_id: UUID
    note: str | None = None


class DeclineRequest(BaseModel):
    reason: str | None = None


class PrepareRequest(BaseModel):
    bed_type: str | None = None
    team_leader: str | None = None
    notes: str | None = None
    eta_minutes: int | None = None


class AcceptanceOut(BaseModel):
    status: Literal["accepted", "declined"]
    decision_by: str | None = None
    hospital_id: UUID | None = None
    recommended_hospital_id: UUID | None = None
    reason: str | None = None
    prepared_at: str | None = None
