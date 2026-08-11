from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Device, User
from ..schemas.device import DeviceCreate


def register_device(db: Session, payload: DeviceCreate, user: User) -> Device:
    device = Device(owner_id=user.id, label=payload.label)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def validate_owned_device(
    db: Session, device_id: UUID | None, user: User
) -> Device | None:
    """Return the device if ``device_id`` is owned by ``user``; else 403."""
    if device_id is None:
        return None
    device = db.get(Device, device_id)
    if device is None or device.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device not registered or not owned",
        )
    return device
