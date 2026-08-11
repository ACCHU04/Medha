from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ambulance, User


def get_assigned_ambulance(db: Session, user: User) -> Ambulance:
    ambulance = db.scalars(
        select(Ambulance).where(Ambulance.assigned_to_id == user.id).limit(1)
    ).first()
    if ambulance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ambulance assigned to this paramedic",
        )
    return ambulance
