from uuid import UUID

from fastapi import APIRouter, Response

from ..dependencies import CurrentUser, DbSession
from ..schemas.ecg import EcgOut
from ..services import ecg as ecg_service

router = APIRouter(prefix="/api/v1/cases", tags=["ecg"])


def _out(ecg) -> EcgOut:
    captured_by = None
    if ecg.captured_by is not None:
        captured_by = ecg.captured_by.username
    return EcgOut(
        id=ecg.id,
        case_id=ecg.case_id,
        captured_by=captured_by,
        captured_at=ecg.captured_at,
        source=ecg.source,
        lead_count=ecg.lead_count,
        paper_speed=ecg.paper_speed,
        waveform=ecg.waveform,
        quality=ecg.quality,
        notes=ecg.notes,
        created_at=ecg.created_at,
    )


@router.get("/{case_id}/ecg", response_model=list[EcgOut])
def list_ecg(
    case_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[EcgOut]:
    records = ecg_service.list_ecg(db, case_id, current_user)
    return [_out(record) for record in records]


@router.get("/{case_id}/ecg/{ecg_id}", response_model=EcgOut)
def get_ecg(
    case_id: UUID,
    ecg_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> EcgOut:
    record = ecg_service.get_ecg(db, case_id, ecg_id, current_user)
    return _out(record)


@router.get("/{case_id}/ecg/{ecg_id}/image")
def get_ecg_image(
    case_id: UUID,
    ecg_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    kind: str = "original",
) -> Response:
    data, media_type = ecg_service.get_image(
        db, case_id, ecg_id, kind, current_user
    )
    return Response(content=data, media_type=media_type)
