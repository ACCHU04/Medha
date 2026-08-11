from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..models import CaseEvent, EmergencyCase, Hospital
from ..models.enums import (
    AmbulanceStatus,
    CaseEventType,
    CaseSeverity,
    CaseStatus,
)
from .eta import nearest_hospital


class TransitionRejected(Exception):
    """Lifecycle rule violation. REST maps to 409; sync maps to a skip."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Transitions are forward-only: the event is legal only from these statuses.
ALLOWED_FROM: dict[CaseEventType, set[CaseStatus]] = {
    CaseEventType.scene_arrival: {CaseStatus.active},
    CaseEventType.transport_start: {CaseStatus.active},
    CaseEventType.hospital_arrival: {CaseStatus.transporting},
    CaseEventType.case_closed: {
        CaseStatus.active,
        CaseStatus.transporting,
        CaseStatus.at_hospital,
    },
    CaseEventType.severity_changed: {
        CaseStatus.active,
        CaseStatus.transporting,
        CaseStatus.at_hospital,
    },
}

STATUS_AFTER: dict[CaseEventType, CaseStatus] = {
    CaseEventType.scene_arrival: CaseStatus.active,
    CaseEventType.transport_start: CaseStatus.transporting,
    CaseEventType.hospital_arrival: CaseStatus.at_hospital,
    CaseEventType.case_closed: CaseStatus.closed,
}

AMBULANCE_AFTER: dict[CaseEventType, AmbulanceStatus] = {
    CaseEventType.transport_start: AmbulanceStatus.transporting,
    CaseEventType.hospital_arrival: AmbulanceStatus.available,
    CaseEventType.case_closed: AmbulanceStatus.available,
}


def apply_transition(
    db: Session,
    case: EmergencyCase,
    event_type: CaseEventType,
    *,
    severity: CaseSeverity | None = None,
    note: str | None = None,
    hospital_id: UUID | None = None,
    event_id: UUID | None = None,
    device_id: UUID | None = None,
    hlc: str | None = None,
) -> CaseEvent:
    """Validate and apply one lifecycle transition atomically.

    Mutates ``case`` (status/severity/hospital_id/closed_at), the assigned
    ambulance status, and appends a ``case_events`` row. Does not commit;
    callers own the transaction so REST and sync share identical behavior.
    """
    if event_type not in ALLOWED_FROM:
        raise TransitionRejected(f"unsupported transition type: {event_type.value}")
    if case.status == CaseStatus.closed:
        raise TransitionRejected("case is already closed")
    if case.status not in ALLOWED_FROM[event_type]:
        raise TransitionRejected(
            f"{event_type.value} not allowed from status {case.status.value}"
        )
    if event_type != CaseEventType.severity_changed:
        already = (
            db.query(CaseEvent)
            .filter_by(case_id=case.id, event_type=event_type)
            .first()
        )
        if already is not None:
            raise TransitionRejected(f"{event_type.value} already recorded")

    if event_type == CaseEventType.transport_start:
        previous_hospital = case.hospital_id
        if hospital_id is not None:
            hospital = db.get(Hospital, hospital_id)
            if hospital is None:
                raise TransitionRejected("destination hospital not found")
            case.hospital_id = hospital.id
        elif case.hospital_id is None:
            # Fallback: nearest hospital with coordinates.
            hospital = nearest_hospital(db, case)
            if hospital is not None:
                case.hospital_id = hospital.id
    elif hospital_id is not None:
        raise TransitionRejected("hospital_id only allowed on transport_start")

    if event_type == CaseEventType.severity_changed:
        if severity is None:
            raise TransitionRejected("severity required for severity_changed")
        if severity == case.severity:
            raise TransitionRejected("severity unchanged")
        changes = {
            "severity": {
                "previous": case.severity.value if case.severity else None,
                "incoming": severity.value,
            }
        }
    else:
        changes = {
            "status": {
                "previous": case.status.value,
                "incoming": STATUS_AFTER[event_type].value,
            }
        }
        if event_type == CaseEventType.transport_start:
            changes["hospital_id"] = {
                "previous": str(previous_hospital) if previous_hospital else None,
                "incoming": str(case.hospital_id) if case.hospital_id else None,
            }

    if note:
        changes["note"] = note

    event = CaseEvent(
        id=event_id or uuid4(),
        case_id=case.id,
        event_type=event_type,
        payload={"changes": changes},
        device_id=device_id,
        hlc=hlc,
        created_at=_utcnow(),
    )
    db.add(event)

    if event_type == CaseEventType.severity_changed:
        case.severity = severity
    else:
        case.status = STATUS_AFTER[event_type]
        if event_type == CaseEventType.case_closed:
            case.closed_at = _utcnow()

    ambulance_status = AMBULANCE_AFTER.get(event_type)
    if ambulance_status is not None and case.ambulance is not None:
        case.ambulance.status = ambulance_status

    return event
