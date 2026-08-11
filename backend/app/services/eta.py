"""Prototype ETA + nearest-hospital helpers (Feature 3).

The ETA is a straight-line haversine distance at a constant average speed.
It is explicitly a prototype calculation — production would use a real
routing/navigation provider.
"""

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ambulance, EmergencyCase, GpsPoint, Hospital

AVG_SPEED_KMH = 30.0
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def eta_minutes(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    speed_kmh: float = AVG_SPEED_KMH,
) -> int:
    """Prototype ETA in whole minutes at constant speed."""
    km = haversine_km(lat1, lon1, lat2, lon2)
    return max(0, math.ceil((km / speed_kmh) * 60.0))


def latest_gps(db: Session, case_id: UUID) -> GpsPoint | None:
    """Newest recorded GPS fix for a case."""
    return db.scalars(
        select(GpsPoint)
        .where(GpsPoint.case_id == case_id)
        .order_by(GpsPoint.recorded_at.desc(), GpsPoint.hlc.desc())
        .limit(1)
    ).first()


def latest_position(db: Session, case: EmergencyCase) -> tuple[float, float] | None:
    """Latest (lat, lon) for a case, falling back to the ambulance's home base."""
    point = latest_gps(db, case.id)
    if point is not None:
        return float(point.latitude), float(point.longitude)
    if case.ambulance is not None and case.ambulance.hospital is not None:
        base = case.ambulance.hospital
        if base.latitude is not None and base.longitude is not None:
            return float(base.latitude), float(base.longitude)
    return None


def case_eta_minutes(db: Session, case: EmergencyCase) -> int | None:
    """Prototype ETA (minutes) from the latest fix to the destination hospital."""
    hospital = case.hospital
    if hospital is None or hospital.latitude is None or hospital.longitude is None:
        return None
    origin = latest_position(db, case)
    if origin is None:
        return None
    return eta_minutes(
        origin[0], origin[1], float(hospital.latitude), float(hospital.longitude)
    )


def _gps_origin_or_base(db: Session, case: EmergencyCase, base: Hospital | None) -> tuple[float, float] | None:
    point = latest_gps(db, case.id)
    if point is not None:
        return float(point.latitude), float(point.longitude)
    if base is not None and base.latitude is not None and base.longitude is not None:
        return float(base.latitude), float(base.longitude)
    return None


def nearest_hospital(
    db: Session,
    case: EmergencyCase,
    exclude_id: UUID | None = None,
    origin: tuple[float, float] | None = None,
) -> Hospital | None:
    """Nearest hospital with coordinates, optionally excluding one (e.g. the declined
    destination). No capability matching yet — that lands in the capability feature."""
    if origin is None:
        origin = _gps_origin_or_base(db, case, case.ambulance.hospital if case.ambulance else None)
    if origin is None:
        return None
    lat0, lon0 = origin
    stmt = select(Hospital).where(
        Hospital.latitude.isnot(None), Hospital.longitude.isnot(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(Hospital.id != exclude_id)
    best: Hospital | None = None
    best_km: float | None = None
    for hospital in db.scalars(stmt):
        km = haversine_km(
            lat0, lon0, float(hospital.latitude), float(hospital.longitude)
        )
        if best is None or km < best_km:
            best, best_km = hospital, km
    return best
