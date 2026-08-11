from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import CurrentUser, DbSession, require_role
from ..models import User
from ..models.enums import UserRole
from ..schemas.vital import VitalCreate, VitalOut
from ..services import vital as vital_service
from ..services.realtime import broadcast_vital

router = APIRouter(prefix="/api/v1/cases", tags=["vitals"])

Paramedic = Annotated[
    User, Depends(require_role(UserRole.paramedic))
]


@router.post(
    "/{case_id}/vitals",
    response_model=VitalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_vital(
    case_id: UUID,
    payload: VitalCreate,
    db: DbSession,
    _paramedic: Paramedic,
) -> VitalOut:
    vital = vital_service.create_vital(db, case_id, payload, _paramedic)
    await broadcast_vital(case_id, vital)
    return vital


@router.get("/{case_id}/vitals", response_model=list[VitalOut])
def list_vitals(
    case_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[VitalOut]:
    case = vital_service.get_case_or_404(db, case_id)
    if current_user.role == UserRole.paramedic and case.created_by_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this case",
        )
    return vital_service.list_vitals(db, case_id)
