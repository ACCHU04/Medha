from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Hospital
from ..schemas.hospital import HospitalCreate


def create_hospital(db: Session, payload: HospitalCreate) -> Hospital:
    hospital = Hospital(**payload.model_dump())
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


def list_hospitals(db: Session) -> list[Hospital]:
    return list(db.scalars(select(Hospital).order_by(Hospital.name)))
