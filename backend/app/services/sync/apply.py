"""Server-side application of offline device batches.

Two-pass (dependency-ordered) apply with per-operation isolation:
- each op runs in its own savepoint; a bad op is skipped, the rest apply;
- append-only entities (vital, event) dedupe by primary key;
- mutable entities (patient, case) resolve by HLC last-writer-wins, with the
  previous state written to ``case_events`` as an audit trail.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Ambulance,
    CaseEvent,
    Device,
    EmergencyCase,
    GpsPoint,
    Hospital,
    Patient,
    Vital,
)
from ...models.enums import CaseEventType, CaseSeverity, CaseStatus
from ...schemas.gps import GpsCreate
from ...schemas.patient import PatientCreate
from ...schemas.sync import SyncOp
from ...schemas.vital import VitalCreate
from ..case_lifecycle import TransitionRejected, apply_transition
from .hlc import HlcTimestamp, hlc_cmp

_ENTITY_ORDER = {
    "patient": 0,
    "case": 1,
    "transition": 2,
    "vital": 2,
    "event": 2,
    "gps": 2,
}


class OpRejected(Exception):
    """Permanent per-op rejection: validation or authorization failure."""


@dataclass
class ApplyOutcome:
    applied: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    vitals: list[Vital] = field(default_factory=list)
    events: list[CaseEvent] = field(default_factory=list)
    gps: list[GpsPoint] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _device_or_reject(db: Session, user, op: SyncOp) -> Device:
    device = db.get(Device, op.device_id)
    if device is None or device.owner_id != user.id:
        raise OpRejected("device not registered or not owned by this user")
    return device


def _validate_hlc_device(op: SyncOp) -> None:
    try:
        embedded = HlcTimestamp.from_string(op.hlc).device_id
    except (ValueError, IndexError):
        raise OpRejected("malformed hlc") from None
    if embedded != str(op.device_id):
        raise OpRejected("hlc device does not match op device")


def _parse_uuid(value, label: str) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise OpRejected(f"invalid {label}") from None


def _get_case(db: Session, case_id, user) -> EmergencyCase:
    parsed = _parse_uuid(case_id, "case_id")
    if parsed is None:
        raise OpRejected("missing case reference")
    case = db.get(EmergencyCase, parsed)
    if case is None:
        raise OpRejected("referenced case not found")
    if case.created_by_id != user.id:
        raise OpRejected("not authorized for this case")
    return case


def _add_audit_event(
    db: Session,
    case: EmergencyCase,
    event_type: CaseEventType,
    device: Device,
    hlc: str,
    payload: dict,
) -> None:
    db.add(
        CaseEvent(
            case_id=case.id,
            event_type=event_type,
            payload=payload,
            device_id=device.id,
            hlc=hlc,
            created_at=_utcnow(),
        )
    )


def _apply_patient(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)
    try:
        data = PatientCreate(**op.data)
    except ValidationError as exc:
        raise OpRejected(f"validation failed: {exc.errors()[0]['msg']}") from None

    existing = db.get(Patient, op.id)
    if existing is not None:
        if existing.created_by_id != user.id:
            raise OpRejected("not authorized for this patient")
        if existing.hlc is not None and hlc_cmp(op.hlc, existing.hlc) <= 0:
            raise OpRejected("older or duplicate")
        previous = {
            "name": existing.name,
            "age": existing.age,
            "sex": existing.sex,
            "blood_type": existing.blood_type,
            "medical_history": existing.medical_history,
        }
        existing.name = data.name
        existing.age = data.age
        existing.sex = data.sex
        existing.blood_type = data.blood_type
        existing.medical_history = data.medical_history
        existing.device_id = device.id
        existing.hlc = op.hlc
        latest_case = (
            db.query(EmergencyCase)
            .filter(EmergencyCase.patient_id == existing.id)
            .order_by(EmergencyCase.created_at.desc())
            .first()
        )
        if latest_case is not None:
            _add_audit_event(
                db,
                latest_case,
                CaseEventType.patient_updated,
                device,
                op.hlc,
                {"previous": previous, "incoming": data.model_dump()},
            )
        return

    db.add(
        Patient(
            id=op.id,
            name=data.name,
            age=data.age,
            sex=data.sex,
            blood_type=data.blood_type,
            medical_history=data.medical_history,
            created_by_id=user.id,
            device_id=device.id,
            hlc=op.hlc,
            created_at=_utcnow(),
        )
    )


def _apply_case(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)

    patient_id = _parse_uuid(op.data.get("patient_id"), "patient_id")
    patient = db.get(Patient, patient_id) if patient_id is not None else None
    if patient is None:
        raise OpRejected("referenced patient not found")

    ambulance_id = _parse_uuid(op.data.get("ambulance_id"), "ambulance_id")
    ambulance = db.get(Ambulance, ambulance_id) if ambulance_id is not None else None
    if ambulance is None:
        raise OpRejected("referenced ambulance not found")
    if ambulance.assigned_to_id != user.id:
        raise OpRejected("paramedic is not assigned to this ambulance")

    severity = None
    if op.data.get("severity") is not None:
        try:
            severity = CaseSeverity(op.data["severity"])
        except ValueError:
            raise OpRejected("invalid severity") from None
    status = CaseStatus.active
    if op.data.get("status") is not None:
        try:
            status = CaseStatus(op.data["status"])
        except ValueError:
            raise OpRejected("invalid status") from None
    chief_complaint = op.data.get("chief_complaint")
    hospital_id = _parse_uuid(op.data.get("hospital_id"), "hospital_id")
    if hospital_id is not None and db.get(Hospital, hospital_id) is None:
        raise OpRejected("referenced hospital not found")

    existing = db.get(EmergencyCase, op.id)
    if existing is not None:
        if existing.created_by_id != user.id:
            raise OpRejected("not authorized for this case")
        if existing.hlc is not None and hlc_cmp(op.hlc, existing.hlc) <= 0:
            raise OpRejected("older or duplicate")

        previous_status = existing.status
        previous_severity = existing.severity
        changed = {}
        if status != previous_status:
            changed["status"] = {"previous": previous_status.value, "incoming": status.value}
        if severity != previous_severity:
            changed["severity"] = {
                "previous": previous_severity.value if previous_severity else None,
                "incoming": severity.value if severity else None,
            }
        if chief_complaint != existing.chief_complaint:
            changed["chief_complaint"] = {
                "previous": existing.chief_complaint,
                "incoming": chief_complaint,
            }
        if hospital_id != existing.hospital_id:
            changed["hospital_id"] = {
                "previous": str(existing.hospital_id) if existing.hospital_id else None,
                "incoming": str(hospital_id) if hospital_id else None,
            }

        if changed:
            if status == CaseStatus.closed and "status" in changed:
                _add_audit_event(
                    db, existing, CaseEventType.case_closed, device, op.hlc,
                    {"changes": changed},
                )
            elif "severity" in changed:
                _add_audit_event(
                    db, existing, CaseEventType.severity_changed, device, op.hlc,
                    {"changes": changed},
                )
            else:
                _add_audit_event(
                    db, existing, CaseEventType.state_updated, device, op.hlc,
                    {"changes": changed},
                )

        existing.status = status
        existing.severity = severity
        existing.chief_complaint = chief_complaint
        existing.hospital_id = hospital_id
        existing.device_id = device.id
        existing.hlc = op.hlc
        if status == CaseStatus.closed and existing.closed_at is None:
            existing.closed_at = _utcnow()
        return

    db.add(
        EmergencyCase(
            id=op.id,
            patient_id=patient.id,
            ambulance_id=ambulance.id,
            hospital_id=hospital_id,
            severity=severity,
            status=status,
            chief_complaint=chief_complaint,
            created_by_id=user.id,
            device_id=device.id,
            hlc=op.hlc,
            created_at=_utcnow(),
            closed_at=_utcnow() if status == CaseStatus.closed else None,
        )
    )


def _apply_vital(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)
    case = _get_case(db, op.data.get("case_id"), user)
    if db.get(Vital, op.id) is not None:
        raise OpRejected("duplicate")

    payload = {key: value for key, value in op.data.items() if key != "case_id"}
    try:
        data = VitalCreate(**payload)
    except ValidationError as exc:
        raise OpRejected(f"validation failed: {exc.errors()[0]['msg']}") from None

    db.add(
        Vital(
            id=op.id,
            case_id=case.id,
            timestamp=data.timestamp or _utcnow(),
            heart_rate=data.heart_rate,
            spo2=data.spo2,
            systolic_bp=data.systolic_bp,
            diastolic_bp=data.diastolic_bp,
            temperature=data.temperature,
            respiratory_rate=data.respiratory_rate,
            source=data.source,
            device_id=device.id,
            hlc=op.hlc,
        )
    )


def _apply_gps(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)
    case = _get_case(db, op.data.get("case_id"), user)
    if case.status == CaseStatus.closed:
        raise OpRejected("case is closed")
    if db.get(GpsPoint, op.id) is not None:
        raise OpRejected("duplicate")

    try:
        data = GpsCreate(**op.data)
    except ValidationError as exc:
        raise OpRejected(f"validation failed: {exc.errors()[0]['msg']}") from None
    if data.ambulance_id != case.ambulance_id:
        raise OpRejected("ambulance does not match case")

    db.add(
        GpsPoint(
            id=op.id,
            case_id=case.id,
            ambulance_id=data.ambulance_id,
            latitude=data.latitude,
            longitude=data.longitude,
            recorded_at=data.recorded_at or _utcnow(),
            created_at=_utcnow(),
            device_id=device.id,
            hlc=op.hlc,
        )
    )


def _apply_event(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)
    case = _get_case(db, op.data.get("case_id"), user)
    if db.get(CaseEvent, op.id) is not None:
        raise OpRejected("duplicate")

    event_type = op.data.get("event_type")
    try:
        event_type = CaseEventType(event_type)
    except (ValueError, TypeError):
        raise OpRejected("invalid event_type") from None
    payload = op.data.get("payload")

    db.add(
        CaseEvent(
            id=op.id,
            case_id=case.id,
            event_type=event_type,
            payload=payload,
            device_id=device.id,
            hlc=op.hlc,
            created_at=_utcnow(),
        )
    )


def _apply_transition(db: Session, user, op: SyncOp) -> None:
    device = _device_or_reject(db, user, op)
    _validate_hlc_device(op)
    case = _get_case(db, op.data.get("case_id"), user)
    if db.get(CaseEvent, op.id) is not None:
        raise OpRejected("duplicate")

    try:
        event_type = CaseEventType(op.data.get("event_type"))
    except (ValueError, TypeError):
        raise OpRejected("invalid event_type") from None

    severity = None
    if op.data.get("severity") is not None:
        try:
            severity = CaseSeverity(op.data["severity"])
        except ValueError:
            raise OpRejected("invalid severity") from None

    hospital_id = _parse_uuid(op.data.get("hospital_id"), "hospital_id")

    try:
        apply_transition(
            db,
            case,
            event_type,
            severity=severity,
            note=op.data.get("note"),
            hospital_id=hospital_id,
            event_id=op.id,
            device_id=device.id,
            hlc=op.hlc,
        )
    except TransitionRejected as exc:
        raise OpRejected(str(exc)) from None


_APPLY = {
    "patient": _apply_patient,
    "case": _apply_case,
    "transition": _apply_transition,
    "vital": _apply_vital,
    "event": _apply_event,
    "gps": _apply_gps,
}


def _op_sort_key(op: SyncOp):
    order = _ENTITY_ORDER.get(op.entity, 99)
    if op.entity == "transition":
        # Lifecycle transitions are order-sensitive: sort by HLC (canonical
        # total order) so a full offline lifecycle replays in the right order
        # regardless of client id assignment.
        return (order, op.hlc or "", str(op.id))
    return (order, str(op.id))


def apply_batch(db: Session, user, ops: list[SyncOp]) -> ApplyOutcome:
    """Apply an offline device batch with per-op isolation and HLC conflict rules."""
    outcome = ApplyOutcome()
    ordered = sorted(ops, key=_op_sort_key)
    for op in ordered:
        handler = _APPLY.get(op.entity)
        if handler is None:
            outcome.skipped.append(
                {"id": str(op.id), "entity": op.entity, "reason": "unknown entity"}
            )
            continue
        savepoint = db.begin_nested()
        try:
            handler(db, user, op)
            savepoint.commit()
            outcome.applied.append({"id": str(op.id), "entity": op.entity})
            if op.entity == "vital":
                vital = db.get(Vital, op.id)
                if vital is not None:
                    outcome.vitals.append(vital)
            if op.entity == "transition":
                event = db.get(CaseEvent, op.id)
                if event is not None:
                    outcome.events.append(event)
            if op.entity == "gps":
                point = db.get(GpsPoint, op.id)
                if point is not None:
                    outcome.gps.append(point)
        except OpRejected as exc:
            savepoint.rollback()
            outcome.skipped.append(
                {"id": str(op.id), "entity": op.entity, "reason": str(exc)}
            )
        except Exception as exc:  # noqa: BLE001 — isolation guarantees
            savepoint.rollback()
            outcome.skipped.append(
                {"id": str(op.id), "entity": op.entity, "reason": f"apply failed: {exc}"}
            )
    db.commit()
    return outcome


def _patient_data(patient: Patient) -> dict:
    return {
        "name": patient.name,
        "age": patient.age,
        "sex": patient.sex,
        "blood_type": patient.blood_type,
        "medical_history": patient.medical_history,
    }


def _case_data(case: EmergencyCase) -> dict:
    return {
        "patient_id": str(case.patient_id),
        "ambulance_id": str(case.ambulance_id) if case.ambulance_id else None,
        "hospital_id": str(case.hospital_id) if case.hospital_id else None,
        "severity": case.severity.value if case.severity else None,
        "status": case.status.value,
        "chief_complaint": case.chief_complaint,
    }


def _vital_data(vital: Vital) -> dict:
    return {
        "case_id": str(vital.case_id),
        "timestamp": vital.timestamp.isoformat() if vital.timestamp else None,
        "heart_rate": vital.heart_rate,
        "spo2": vital.spo2,
        "systolic_bp": vital.systolic_bp,
        "diastolic_bp": vital.diastolic_bp,
        "temperature": float(vital.temperature) if vital.temperature is not None else None,
        "respiratory_rate": vital.respiratory_rate,
        "source": vital.source.value,
    }


def _event_data(event: CaseEvent) -> dict:
    return {
        "case_id": str(event.case_id),
        "event_type": event.event_type.value,
        "payload": event.payload,
    }


def pull_changes(
    db: Session,
    user,
    since: str | None = None,
    entity: str | None = None,
    case_id: UUID | None = None,
) -> list[dict]:
    """Pull syncable rows newer than the ``since`` HLC cursor for accessible cases."""
    is_paramedic = user.role.value == "paramedic"
    changes: list[dict] = []

    if entity in (None, "patient"):
        stmt = select(Patient).where(Patient.hlc.isnot(None))
        if since:
            stmt = stmt.where(Patient.hlc > since)
        if is_paramedic:
            stmt = stmt.where(Patient.created_by_id == user.id)
        if case_id is not None:
            case = db.get(EmergencyCase, case_id)
            if case is None:
                return changes
            stmt = stmt.where(Patient.id == case.patient_id)
        for patient in db.scalars(stmt):
            changes.append(
                {
                    "entity": "patient",
                    "id": str(patient.id),
                    "device_id": str(patient.device_id) if patient.device_id else None,
                    "hlc": patient.hlc,
                    "data": _patient_data(patient),
                }
            )

    if entity in (None, "case"):
        stmt = select(EmergencyCase).where(EmergencyCase.hlc.isnot(None))
        if since:
            stmt = stmt.where(EmergencyCase.hlc > since)
        if is_paramedic:
            stmt = stmt.where(EmergencyCase.created_by_id == user.id)
        if case_id is not None:
            stmt = stmt.where(EmergencyCase.id == case_id)
        for case in db.scalars(stmt):
            changes.append(
                {
                    "entity": "case",
                    "id": str(case.id),
                    "device_id": str(case.device_id) if case.device_id else None,
                    "hlc": case.hlc,
                    "data": _case_data(case),
                }
            )

    if entity in (None, "vital"):
        stmt = (
            select(Vital)
            .join(EmergencyCase, Vital.case_id == EmergencyCase.id)
            .where(Vital.hlc.isnot(None))
        )
        if since:
            stmt = stmt.where(Vital.hlc > since)
        if is_paramedic:
            stmt = stmt.where(EmergencyCase.created_by_id == user.id)
        if case_id is not None:
            stmt = stmt.where(Vital.case_id == case_id)
        for vital in db.scalars(stmt):
            changes.append(
                {
                    "entity": "vital",
                    "id": str(vital.id),
                    "device_id": str(vital.device_id) if vital.device_id else None,
                    "hlc": vital.hlc,
                    "data": _vital_data(vital),
                }
            )

    if entity in (None, "event"):
        stmt = (
            select(CaseEvent)
            .join(EmergencyCase, CaseEvent.case_id == EmergencyCase.id)
            .where(CaseEvent.hlc.isnot(None))
        )
        if since:
            stmt = stmt.where(CaseEvent.hlc > since)
        if is_paramedic:
            stmt = stmt.where(EmergencyCase.created_by_id == user.id)
        if case_id is not None:
            stmt = stmt.where(CaseEvent.case_id == case_id)
        for event in db.scalars(stmt):
            changes.append(
                {
                    "entity": "event",
                    "id": str(event.id),
                    "device_id": str(event.device_id) if event.device_id else None,
                    "hlc": event.hlc,
                    "data": _event_data(event),
                }
            )

    changes.sort(key=lambda change: change["hlc"] or "")
    return changes
