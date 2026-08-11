"""Read path for digitized ECG records (Feature 4).

Writes happen only through the offline sync outbox (``entity="ecg"`` in
/sync/push); this service exposes list/detail/image reads to the ambulance
simulator and hospital dashboard with the same access rules as vitals:
a paramedic sees only their own cases, hospital staff see any case.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EcgTracing, EmergencyCase, User
from ..models.enums import UserRole

_WEBP_MAGIC = b"WEBP"


def _case_or_404(db: Session, case_id: UUID) -> EmergencyCase:
    case = db.get(EmergencyCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case not found"
        )
    return case


def _check_access(case: EmergencyCase, user: User) -> None:
    if user.role == UserRole.paramedic and case.created_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this case",
        )


def _ecg_or_404(db: Session, case_id: UUID, ecg_id: UUID) -> EcgTracing:
    ecg = db.get(EcgTracing, ecg_id)
    if ecg is None or ecg.case_id != case_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ECG record not found"
        )
    return ecg


def list_ecg(db: Session, case_id: UUID, user: User) -> list[EcgTracing]:
    case = _case_or_404(db, case_id)
    _check_access(case, user)
    return list(
        db.scalars(
            select(EcgTracing)
            .where(EcgTracing.case_id == case_id)
            .order_by(EcgTracing.captured_at.desc())
        )
    )


def get_ecg(db: Session, case_id: UUID, ecg_id: UUID, user: User) -> EcgTracing:
    case = _case_or_404(db, case_id)
    _check_access(case, user)
    return _ecg_or_404(db, case_id, ecg_id)


def get_image(
    db: Session, case_id: UUID, ecg_id: UUID, kind: str, user: User
) -> tuple[bytes, str]:
    """Return (bytes, media_type) for the requested image variant."""
    ecg = get_ecg(db, case_id, ecg_id, user)
    if kind == "original":
        data = ecg.image_original
    elif kind == "normalized":
        data = ecg.image_normalized
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="kind must be 'original' or 'normalized'",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not available"
        )
    return data, _media_type(data)


def _media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[8:12] == _WEBP_MAGIC:
        return "image/webp"
    return "application/octet-stream"
