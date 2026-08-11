import uuid
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EmergencyCase, User, Vital
from ..models.user import utcnow
from ..schemas.vital import VitalCreate
from .device import validate_owned_device


def get_case_or_404(db: Session, case_id: UUID) -> EmergencyCase:
    case = db.get(EmergencyCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )
    return case


def create_vital(db: Session, case_id: UUID, payload: VitalCreate, user: User) -> Vital:
    case = get_case_or_404(db, case_id)
    if case.created_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this case",
        )
    device = validate_owned_device(db, payload.device_id, user)
    vital = Vital(
        id=payload.id if payload.id is not None else uuid.uuid4(),
        case_id=case.id,
        timestamp=payload.timestamp or utcnow(),
        heart_rate=payload.heart_rate,
        spo2=payload.spo2,
        systolic_bp=payload.systolic_bp,
        diastolic_bp=payload.diastolic_bp,
        temperature=payload.temperature,
        respiratory_rate=payload.respiratory_rate,
        source=payload.source,
        device_id=device.id if device else None,
        hlc=payload.hlc,
    )
    db.add(vital)
    db.commit()
    db.refresh(vital)
    return vital


def list_vitals(db: Session, case_id: UUID, limit: int = 100) -> list[Vital]:
    get_case_or_404(db, case_id)
    stmt = (
        select(Vital)
        .where(Vital.case_id == case_id)
        .order_by(Vital.timestamp.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
