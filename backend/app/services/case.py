import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Ambulance,
    CaseEvent,
    EmergencyCase,
    GpsPoint,
    Hospital,
    Patient,
    User,
)
from ..models.enums import CaseAcceptance, CaseEventType, CaseStatus
from ..schemas.ambulance import AmbulanceOut
from ..schemas.case import AlternativeHospital, CaseCreate, CaseOut, RecommendationOut
from ..schemas.hospital import HospitalOut
from ..schemas.patient import PatientOut
from .device import validate_owned_device
from .eta import case_eta_minutes, case_eta_minutes_from_point
from .routing import recommend_hospital

_LOAD_DETAILS = (
    selectinload(EmergencyCase.patient),
    selectinload(EmergencyCase.ambulance).selectinload(Ambulance.hospital),
    selectinload(EmergencyCase.hospital),
    selectinload(EmergencyCase.recommended_hospital),
)


def _get_patient_or_404(db: Session, patient_id: UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return patient


def _get_ambulance_or_404(db: Session, ambulance_id: UUID) -> Ambulance:
    ambulance = db.get(Ambulance, ambulance_id)
    if ambulance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ambulance not found",
        )
    return ambulance


def create_case(db: Session, payload: CaseCreate, user: User) -> EmergencyCase:
    _get_patient_or_404(db, payload.patient_id)
    ambulance = _get_ambulance_or_404(db, payload.ambulance_id)
    if ambulance.assigned_to_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Paramedic is not assigned to this ambulance",
        )

    device = validate_owned_device(db, payload.device_id, user)
    case = EmergencyCase(
        id=payload.id if payload.id is not None else uuid.uuid4(),
        patient_id=payload.patient_id,
        ambulance_id=ambulance.id,
        chief_complaint=payload.chief_complaint,
        severity=payload.severity,
        status=CaseStatus.active,
        created_by_id=user.id,
        device_id=device.id if device else None,
        hlc=payload.hlc,
    )
    db.add(case)
    db.commit()
    case = db.scalar(
        select(EmergencyCase)
        .where(EmergencyCase.id == case.id)
        .options(*_LOAD_DETAILS)
    )
    return case


def get_case(db: Session, case_id: UUID) -> EmergencyCase:
    case = db.scalar(
        select(EmergencyCase)
        .where(EmergencyCase.id == case_id)
        .options(*_LOAD_DETAILS)
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )
    return case


def list_open_cases(db: Session, user: User) -> list[EmergencyCase]:
    stmt = (
        select(EmergencyCase)
        .where(EmergencyCase.status != CaseStatus.closed)
        .order_by(EmergencyCase.created_at.desc())
        .options(*_LOAD_DETAILS)
    )
    if user.role.value == "paramedic":
        stmt = stmt.where(EmergencyCase.created_by_id == user.id)
    return list(db.scalars(stmt))


def _latest_gps_by_case(
    db: Session, case_ids: list[UUID]
) -> dict[UUID, GpsPoint]:
    """One query for the newest GPS fix per case (DISTINCT ON in Postgres)."""
    if not case_ids:
        return {}
    rows = db.execute(
        select(GpsPoint)
        .where(GpsPoint.case_id.in_(case_ids))
        .distinct(GpsPoint.case_id)
        .order_by(GpsPoint.case_id, GpsPoint.recorded_at.desc(), GpsPoint.hlc.desc())
    ).scalars()
    return {point.case_id: point for point in rows}


def _serialize_recommendation(
    db: Session, case: EmergencyCase
) -> RecommendationOut | None:
    """'Why this hospital?' payload. Computed only when there is no locked
    destination (pre-transport) or after a decline (recommended fallback)."""
    if case.hospital_id is not None and case.recommended_hospital_id is None:
        return None
    # After a decline the fallback was computed excluding the current
    # destination; recompute with the same exclusion so the payload agrees
    # with the stored recommended_hospital_id.
    rec = recommend_hospital(db, case, exclude_id=case.hospital_id)
    if rec is None:
        return None
    return RecommendationOut(
        hospital=HospitalOut.model_validate(rec.hospital),
        matched_capabilities=rec.matched_capabilities,
        distance_km=round(rec.distance_km, 2),
        alternatives=[
            AlternativeHospital(
                hospital=HospitalOut.model_validate(hospital),
                distance_km=round(km, 2),
            )
            for hospital, km in rec.alternatives
        ],
    )


def serialize_case(db: Session, case: EmergencyCase, eta: int | None = None) -> CaseOut:
    """Build a CaseOut, computing the prototype ETA when a destination + fix exist."""
    return CaseOut(
        id=case.id,
        patient_id=case.patient_id,
        ambulance_id=case.ambulance_id,
        hospital_id=case.hospital_id,
        severity=case.severity,
        status=case.status,
        chief_complaint=case.chief_complaint,
        created_by_id=case.created_by_id,
        created_at=case.created_at,
        closed_at=case.closed_at,
        acceptance=case.acceptance_status,
        decision_by_id=case.decision_by_id,
        decision_at=case.decision_at,
        decline_reason=case.decline_reason,
        recommended_hospital_id=case.recommended_hospital_id,
        prepared_at=case.prepared_at,
        preparation_notes=case.preparation_notes,
        route_geojson=case.route_geojson,
        patient=PatientOut.model_validate(case.patient) if case.patient else None,
        ambulance=AmbulanceOut.model_validate(case.ambulance) if case.ambulance else None,
        destination_hospital=(
            HospitalOut.model_validate(case.hospital) if case.hospital else None
        ),
        recommended_hospital=(
            HospitalOut.model_validate(case.recommended_hospital)
            if case.recommended_hospital
            else None
        ),
        recommendation=_serialize_recommendation(db, case),
        eta_minutes=eta if eta is not None else case_eta_minutes(db, case),
    )


def serialize_cases(db: Session, cases: list[EmergencyCase]) -> list[CaseOut]:
    """Bulk serialization with a single latest-GPS query for the ETA column."""
    gps_by_case = _latest_gps_by_case(db, [case.id for case in cases])
    result: list[CaseOut] = []
    for case in cases:
        point = gps_by_case.get(case.id)
        eta = None
        if point is not None or case.hospital is not None:
            eta = case_eta_minutes_from_point(db, case, point)
        result.append(serialize_case(db, case, eta=eta))
    return result


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _guard_transporting(case: EmergencyCase) -> None:
    if case.status != CaseStatus.transporting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="case is not in transport",
        )


def accept_case(
    db: Session,
    case: EmergencyCase,
    user: User,
    hospital_id: UUID,
    note: str | None = None,
) -> CaseEvent:
    """Hospital confirms it will take the patient. Destination is locked to the
    accepting hospital. Returns the audit event; caller owns commit + broadcast."""
    _guard_transporting(case)
    if case.acceptance_status == CaseAcceptance.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="case already accepted"
        )
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found"
        )
    if user.hospital_id is not None and user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="decision not allowed for this hospital",
        )

    case.hospital_id = hospital.id
    case.acceptance_status = CaseAcceptance.accepted
    case.decision_by_id = user.id
    case.decision_at = _utcnow()
    case.decline_reason = None
    event = CaseEvent(
        case_id=case.id,
        event_type=CaseEventType.hospital_accept,
        payload={
            "hospital_id": str(hospital.id),
            "hospital_name": hospital.name,
            "note": note,
            "by": user.username,
        },
        created_at=_utcnow(),
    )
    db.add(event)
    return event


def decline_case(
    db: Session,
    case: EmergencyCase,
    user: User,
    reason: str | None = None,
) -> CaseEvent:
    """Hospital cannot take the patient. Recommends the next-nearest hospital."""
    _guard_transporting(case)
    if case.acceptance_status == CaseAcceptance.declined:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="case already declined"
        )
    if case.hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="no destination to decline"
        )
    hospital = db.get(Hospital, case.hospital_id)
    case.acceptance_status = CaseAcceptance.declined
    case.decision_by_id = user.id
    case.decision_at = _utcnow()
    case.decline_reason = reason

    recommended = recommend_hospital(db, case, exclude_id=case.hospital_id)
    case.recommended_hospital_id = recommended.hospital.id if recommended else None
    event = CaseEvent(
        case_id=case.id,
        event_type=CaseEventType.hospital_decline,
        payload={
            "hospital_id": str(hospital.id) if hospital else None,
            "hospital_name": hospital.name if hospital else None,
            "recommended_hospital_id": (
                str(recommended.hospital.id) if recommended else None
            ),
            "recommended_hospital_name": (
                recommended.hospital.name if recommended else None
            ),
            "recommended_capabilities": (
                recommended.matched_capabilities if recommended else []
            ),
            "recommended_distance_km": (
                round(recommended.distance_km, 2) if recommended else None
            ),
            "reason": reason,
            "by": user.username,
        },
        created_at=_utcnow(),
    )
    db.add(event)
    return event


def prepare_case(
    db: Session,
    case: EmergencyCase,
    user: User | None = None,
    *,
    auto: bool = False,
    bed_type: str | None = None,
    team_leader: str | None = None,
    notes: str | None = None,
    eta_minutes: int | None = None,
    device_id=None,
    hlc: str | None = None,
) -> CaseEvent:
    """Hospital readies a bed/team ahead of arrival (accept first).

    ``auto=True`` marks a geofence-triggered preparation (the geofence module
    pre-checks the guards, so a race conflict is a silent no-op there); the
    event payload then carries ``"auto": true`` and ``by`` falls back to
    ``"geofence"`` when no user acts.
    """
    _guard_transporting(case)
    if case.acceptance_status != CaseAcceptance.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="hospital must accept the case first",
        )
    if case.prepared_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="case already prepared"
        )
    case.prepared_at = _utcnow()
    case.preparation_notes = {
        "bed_type": bed_type,
        "team_leader": team_leader,
        "notes": notes,
        "eta_minutes": eta_minutes,
        "auto": auto,
    }
    event = CaseEvent(
        case_id=case.id,
        event_type=CaseEventType.hospital_prepare,
        payload={
            "bed_type": bed_type,
            "team_leader": team_leader,
            "notes": notes,
            "eta_minutes": eta_minutes,
            "auto": auto,
            "by": user.username if user else "geofence",
        },
        device_id=device_id,
        hlc=hlc,
        created_at=_utcnow(),
    )
    db.add(event)
    return event
