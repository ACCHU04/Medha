from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from ..dependencies import CurrentUser, DbSession, require_role
from ..models import User
from ..models.enums import UserRole
from ..schemas.patient import PatientCreate, PatientOut
from ..services import patient as patient_service

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])

Paramedic = Annotated[
    User, Depends(require_role(UserRole.paramedic))
]


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: DbSession,
    _paramedic: Paramedic,
) -> PatientOut:
    return patient_service.create_patient(db, payload, _paramedic)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: UUID, db: DbSession, _: CurrentUser) -> PatientOut:
    return patient_service.get_patient(db, patient_id)
