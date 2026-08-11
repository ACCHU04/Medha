from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from ..dependencies import CurrentUser, DbSession, require_role
from ..models import User
from ..models.enums import UserRole
from ..schemas.device import DeviceCreate, DeviceOut
from ..schemas.sync import (
    AppliedOp,
    SkippedOp,
    SyncChangesResponse,
    SyncPushRequest,
    SyncPushResponse,
)
from ..services import device as device_service
from ..services import case as case_service
from ..services.realtime import broadcast_case_event, broadcast_gps, broadcast_vital
from ..services.sync import apply as sync_apply

router = APIRouter(prefix="/api/v1", tags=["sync"])

Paramedic = Annotated[
    User, Depends(require_role(UserRole.paramedic))
]


@router.post(
    "/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
)
def register_device(
    payload: DeviceCreate,
    db: DbSession,
    _paramedic: Paramedic,
) -> DeviceOut:
    return device_service.register_device(db, payload, _paramedic)


@router.post("/sync/push", response_model=SyncPushResponse)
async def sync_push(
    payload: SyncPushRequest,
    db: DbSession,
    _paramedic: Paramedic,
) -> SyncPushResponse:
    outcome = sync_apply.apply_batch(db, _paramedic, payload.batch)
    for vital in outcome.vitals:
        await broadcast_vital(vital.case_id, vital)
    for event in outcome.events:
        case = case_service.get_case(db, event.case_id)
        serialized = case_service.serialize_case(db, case)
        await broadcast_case_event(event.case_id, event, serialized.model_dump(mode="json"))
    for point in outcome.gps:
        await broadcast_gps(point.case_id, point)
    return SyncPushResponse(
        applied=[
            AppliedOp(id=item["id"], entity=item["entity"])
            for item in outcome.applied
        ],
        skipped=[
            SkippedOp(id=item["id"], entity=item["entity"], reason=item["reason"])
            for item in outcome.skipped
        ],
    )


@router.get("/sync/changes", response_model=SyncChangesResponse)
def sync_changes(
    db: DbSession,
    current_user: CurrentUser,
    since: str | None = None,
    entity: str | None = None,
    case_id: UUID | None = None,
) -> SyncChangesResponse:
    changes = sync_apply.pull_changes(db, current_user, since, entity, case_id)
    return SyncChangesResponse(changes=changes)
