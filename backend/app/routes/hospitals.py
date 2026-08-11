from typing import Annotated

from fastapi import APIRouter, Depends, status

from ..dependencies import CurrentUser, DbSession, require_role
from ..models import User
from ..models.enums import UserRole
from ..schemas.hospital import HospitalCreate, HospitalOut
from ..services import hospital as hospital_service

router = APIRouter(prefix="/api/v1/hospitals", tags=["hospitals"])

HospitalAdmin = Annotated[
    User, Depends(require_role(UserRole.hospital_admin))
]


@router.post(
    "",
    response_model=HospitalOut,
    status_code=status.HTTP_201_CREATED,
)
def create_hospital(
    payload: HospitalCreate,
    db: DbSession,
    _admin: HospitalAdmin,
) -> HospitalOut:
    return hospital_service.create_hospital(db, payload)


@router.get("", response_model=list[HospitalOut])
def list_hospitals(db: DbSession, _: CurrentUser) -> list[HospitalOut]:
    return hospital_service.list_hospitals(db)
