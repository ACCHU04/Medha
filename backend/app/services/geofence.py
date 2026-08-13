"""Geofence-triggered hospital preparation (freeze feature 5).

When a transporting, accepted case's ambulance fix enters the destination
hospital's radius, the case is prepared automatically so the receiving ward
shows ``READY FOR ARRIVAL`` before the ambulance reaches the door.

The check is deliberately additive and idempotent:
- no schema change (``prepared_at`` / ``preparation_notes`` already exist);
- ``prepared_at`` makes repeated fixes inside the radius a no-op;
- a caught conflict never invalidates the GPS fix that triggered it, so the
  sync savepoint that applied the GPS op stays intact.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import CaseEvent, EmergencyCase, GpsPoint
from ..models.enums import CaseAcceptance, CaseStatus
from .case import prepare_case
from .eta import haversine_km

RADIUS_KM = 5.0

_AUTO_NOTES = "Auto-prepared by geofence"


def _within_radius(case: EmergencyCase, point: GpsPoint) -> bool:
    hospital = case.hospital
    if hospital is None or hospital.latitude is None or hospital.longitude is None:
        return False
    return (
        haversine_km(
            float(hospital.latitude),
            float(hospital.longitude),
            point.latitude,
            point.longitude,
        )
        <= RADIUS_KM
    )


def maybe_auto_prepare(
    db: Session,
    case: EmergencyCase,
    point: GpsPoint,
    *,
    device_id=None,
    hlc: str | None = None,
) -> CaseEvent | None:
    """Auto-prepare a case once the fix is inside the destination radius.

    Returns the ``hospital_prepare`` event, or ``None`` when no preparation
    should happen. The caller owns commit (the REST route and the sync
    savepoint both do).
    """
    if case.status != CaseStatus.transporting:
        return None
    if case.acceptance_status != CaseAcceptance.accepted:
        return None
    if case.prepared_at is not None:
        return None
    if not _within_radius(case, point):
        return None

    try:
        return prepare_case(
            db,
            case,
            None,
            auto=True,
            bed_type=None,
            notes=_AUTO_NOTES,
            device_id=device_id,
            hlc=hlc,
        )
    except HTTPException:
        # Race-safe backstop: a concurrent prepare (or a guard trip) is a
        # silent no-op — never reject the GPS fix that got us here.
        return None
