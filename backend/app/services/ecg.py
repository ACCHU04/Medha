"""Read + write path for digitized ECG records (Feature 4).

The write path supports two routes: the offline sync outbox (``entity="ecg"``
in /sync/push) and the REST ``POST /api/v1/cases/{case_id}/ecg`` used when the
device is online. Both share the same validation (base64 image decode with
size/signature checks and a non-trivial waveform).
"""

import base64
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CaseEvent, EcgTracing, EmergencyCase, User
from ..models.enums import CaseEventType, CaseStatus, UserRole
from ..schemas.ecg import EcgSyncPayload

_WEBP_MAGIC = b"WEBP"
_IMAGE_SIZE_CAP = 8 * 1024 * 1024  # 8 MB decoded
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


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


def _decode_image(value: str, label: str) -> bytes:
    """Decode a base64 image payload with size + signature checks."""
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid base64 {label}",
        ) from None
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"empty {label} image"
        )
    if len(data) > _IMAGE_SIZE_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} image exceeds {_IMAGE_SIZE_CAP // (1024 * 1024)} MB",
        )
    if data.startswith(b"RIFF") and data[8:12] == _WEBP_MAGIC:
        return data
    for signature, _fmt in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return data
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{label} is not a recognized image (jpeg/png/webp)",
    )


def _valid_waveform(waveform) -> bool:
    if not isinstance(waveform, dict):
        return False
    channels = waveform.get("channels")
    if not isinstance(channels, list) or not channels:
        return False
    for channel in channels:
        if not isinstance(channel, dict):
            return False
        points = channel.get("points")
        if not isinstance(points, list) or len(points) < 2:
            return False
        for point in points:
            if not (isinstance(point, list) and len(point) == 2):
                return False
    return True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_ecg(
    db: Session,
    case_id: UUID,
    payload: EcgSyncPayload,
    user: User,
    *,
    record_id: UUID | None = None,
    hlc: str | None = None,
    device_id: UUID | None = None,
) -> tuple[EcgTracing, CaseEvent]:
    """Create a digitized ECG record + its ``ecg_added`` audit event.

    Mirrors the sync write path exactly (same validation and payload shape) so
    online REST writes and offline buffered writes behave identically. Returns
    the ``(ecg, event)`` pair; caller owns broadcast.
    """
    case = _case_or_404(db, case_id)
    _check_access(case, user)
    if case.status == CaseStatus.closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="case is closed"
        )
    if not _valid_waveform(payload.waveform):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="waveform must contain at least one channel with points",
        )
    original = _decode_image(payload.image_original, "original")
    normalized = (
        _decode_image(payload.image_normalized, "normalized")
        if payload.image_normalized
        else None
    )

    now = _utcnow()
    ecg = EcgTracing(
        id=record_id or uuid.uuid4(),
        case_id=case.id,
        captured_by_id=user.id,
        captured_at=payload.captured_at or now,
        source=payload.source,
        lead_count=payload.lead_count,
        paper_speed=payload.paper_speed,
        image_original=original,
        image_normalized=normalized,
        waveform=payload.waveform,
        quality=payload.quality,
        notes=payload.notes,
        device_id=device_id,
        hlc=hlc,
        created_at=now,
    )
    db.add(ecg)

    event = CaseEvent(
        case_id=case.id,
        event_type=CaseEventType.ecg_added,
        payload={
            "ecg_id": str(ecg.id),
            "lead_count": payload.lead_count,
            "captured_at": (payload.captured_at or now).isoformat(),
        },
        device_id=device_id,
        hlc=hlc,
        created_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(ecg)
    return ecg, event


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
