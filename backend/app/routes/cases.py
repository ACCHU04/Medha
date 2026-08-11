from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..dependencies import CurrentUser, DbSession, require_role
from ..models import CaseEvent, EmergencyCase, User
from ..models.enums import UserRole
from ..schemas.acceptance import AcceptRequest, DeclineRequest, PrepareRequest
from ..schemas.case import CaseCreate, CaseOut
from ..schemas.case_event import CaseEventOut
from ..schemas.transition import TransitionCreate, TransitionOut
from ..services import case as case_service
from ..services.case_lifecycle import TransitionRejected, apply_transition
from ..services.realtime import broadcast_case_event

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

Paramedic = Annotated[
    User, Depends(require_role(UserRole.paramedic))
]

HospitalStaff = Annotated[
    User, Depends(require_role(UserRole.doctor, UserRole.hospital_admin))
]


def _authorize_case(user: User, case: EmergencyCase) -> None:
    if user.role == UserRole.paramedic and case.created_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this case",
        )


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    db: DbSession,
    _paramedic: Paramedic,
) -> CaseOut:
    case = case_service.create_case(db, payload, _paramedic)
    return case_service.serialize_case(db, case)


@router.get("", response_model=list[CaseOut])
def list_open_cases(db: DbSession, current_user: CurrentUser) -> list[CaseOut]:
    cases = case_service.list_open_cases(db, current_user)
    return case_service.serialize_cases(db, cases)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, db: DbSession, current_user: CurrentUser) -> CaseOut:
    case = case_service.get_case(db, case_id)
    _authorize_case(current_user, case)
    return case_service.serialize_case(db, case)


@router.post("/{case_id}/transitions", response_model=TransitionOut)
async def create_transition(
    case_id: UUID,
    payload: TransitionCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> TransitionOut:
    case = case_service.get_case(db, case_id)
    _authorize_case(current_user, case)
    try:
        event = apply_transition(
            db,
            case,
            payload.event_type,
            severity=payload.severity,
            note=payload.note,
            hospital_id=payload.hospital_id,
        )
    except TransitionRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    db.commit()
    case = case_service.get_case(db, case_id)
    serialized = case_service.serialize_case(db, case)
    await broadcast_case_event(case.id, event, serialized.model_dump(mode="json"))
    return TransitionOut(case=serialized, event=event)


@router.get("/{case_id}/events", response_model=list[CaseEventOut])
def list_case_events(
    case_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[CaseEventOut]:
    case = case_service.get_case(db, case_id)
    _authorize_case(current_user, case)
    stmt = (
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .order_by(CaseEvent.created_at, CaseEvent.hlc)
    )
    return list(db.scalars(stmt))


@router.post("/{case_id}/accept", response_model=TransitionOut)
async def accept_case(
    case_id: UUID,
    payload: AcceptRequest,
    db: DbSession,
    _staff: HospitalStaff,
) -> TransitionOut:
    case = case_service.get_case(db, case_id)
    event = case_service.accept_case(
        db, case, _staff, payload.hospital_id, note=payload.note
    )
    db.commit()
    case = case_service.get_case(db, case_id)
    serialized = case_service.serialize_case(db, case)
    await broadcast_case_event(case.id, event, serialized.model_dump(mode="json"))
    return TransitionOut(case=serialized, event=event)


@router.post("/{case_id}/decline", response_model=TransitionOut)
async def decline_case(
    case_id: UUID,
    payload: DeclineRequest,
    db: DbSession,
    _staff: HospitalStaff,
) -> TransitionOut:
    case = case_service.get_case(db, case_id)
    event = case_service.decline_case(db, case, _staff, reason=payload.reason)
    db.commit()
    case = case_service.get_case(db, case_id)
    serialized = case_service.serialize_case(db, case)
    await broadcast_case_event(case.id, event, serialized.model_dump(mode="json"))
    return TransitionOut(case=serialized, event=event)


@router.post("/{case_id}/prepare", response_model=TransitionOut)
async def prepare_case(
    case_id: UUID,
    payload: PrepareRequest,
    db: DbSession,
    _staff: HospitalStaff,
) -> TransitionOut:
    case = case_service.get_case(db, case_id)
    event = case_service.prepare_case(
        db,
        case,
        _staff,
        bed_type=payload.bed_type,
        team_leader=payload.team_leader,
        notes=payload.notes,
        eta_minutes=payload.eta_minutes,
    )
    db.commit()
    case = case_service.get_case(db, case_id)
    serialized = case_service.serialize_case(db, case)
    await broadcast_case_event(case.id, event, serialized.model_dump(mode="json"))
    return TransitionOut(case=serialized, event=event)
