from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import CaseEventType


class SyncOp(BaseModel):
    """One offline-captured operation from the ambulance device."""

    op: str = "upsert"
    entity: str
    id: UUID
    device_id: UUID
    hlc: str
    data: dict


class SyncPushRequest(BaseModel):
    batch: list[SyncOp]


class AppliedOp(BaseModel):
    id: UUID
    entity: str


class SkippedOp(BaseModel):
    id: UUID
    entity: str
    reason: str


class SyncPushResponse(BaseModel):
    applied: list[AppliedOp]
    skipped: list[SkippedOp]


class SyncChange(BaseModel):
    entity: str
    id: UUID
    device_id: UUID | None
    hlc: str | None
    data: dict


class SyncChangesResponse(BaseModel):
    changes: list[SyncChange]
    case_event_types: list[CaseEventType] = []
