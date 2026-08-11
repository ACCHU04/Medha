from typing import Annotated

from fastapi import APIRouter, Depends

from ..dependencies import DbSession, require_role
from ..models import User
from ..models.enums import UserRole
from ..schemas.ambulance import AmbulanceOut
from ..services import ambulance as ambulance_service

router = APIRouter(prefix="/api/v1/ambulances", tags=["ambulances"])

Paramedic = Annotated[
    User, Depends(require_role(UserRole.paramedic))
]


@router.get("/mine", response_model=AmbulanceOut)
def get_my_ambulance(db: DbSession, _paramedic: Paramedic) -> AmbulanceOut:
    return ambulance_service.get_assigned_ambulance(db, _paramedic)
