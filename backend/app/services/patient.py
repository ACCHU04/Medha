import uuid
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Patient, User
from ..schemas.patient import PatientCreate
from .device import validate_owned_device


def create_patient(db: Session, payload: PatientCreate, user: User) -> Patient:
    device = validate_owned_device(db, payload.device_id, user)
    patient = Patient(
        id=payload.id if payload.id is not None else uuid.uuid4(),
        name=payload.name,
        age=payload.age,
        sex=payload.sex,
        blood_type=payload.blood_type,
        medical_history=payload.medical_history,
        created_by_id=user.id,
        device_id=device.id if device else None,
        hlc=payload.hlc,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def get_patient(db: Session, patient_id: UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return patient
