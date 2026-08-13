"""Prototype ETA + nearest-hospital helpers (Feature 3).

The ETA prefers the OSRM road route captured at ``transport_start`` (stored in
``EmergencyCase.route_geojson``): the remaining journey is the route's total
``duration_s`` scaled by how far along the polyline the latest GPS fix has
traveled. When no routed route is available it falls back to a straight-line
haversine distance at a constant average speed. Both are explicitly prototype
calculations — production would use a validated emergency-routing provider.
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


def route_eta_minutes_from_point(
    case: EmergencyCase,
    point: GpsPoint | None,
) -> int | None:
    """Remaining minutes along the routed polyline (``route_geojson``).

    The simulator generates fixes *on* the stored polyline, so the nearest-vertex
    cumulative length is an exact traveled fraction; for other data sources it is
    still a reasonable prototype approximation. Returns ``None`` when the case has
    no routed route.
    """
    route = case.route_geojson
    if not isinstance(route, dict):
        return None
    duration_s = route.get("duration_s")
    coords = route.get("coordinates")
    if (
        not isinstance(duration_s, (int, float))
        or not isinstance(coords, list)
        or len(coords) < 2
    ):
        return None

    total = 0.0
    seg_lens: list[float] = []
    for a, b in zip(coords, coords[1:]):
        d = haversine_km(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
        seg_lens.append(d)
        total += d

    if point is None or point.latitude is None or point.longitude is None:
        return max(0, math.ceil(float(duration_s) / 60.0))
    if total <= 0:
        return max(0, math.ceil(float(duration_s) / 60.0))

    lat, lng = float(point.latitude), float(point.longitude)
    best_i = 0
    best_d = float("inf")
    for i, (la, lo) in enumerate(coords):
        d = haversine_km(lat, lng, float(la), float(lo))
        if d < best_d:
            best_i, best_d = i, d

    traveled = sum(seg_lens[:best_i])
    frac = min(1.0, traveled / total)
    remaining_s = float(duration_s) * (1.0 - frac)
    return max(0, math.ceil(remaining_s / 60.0))


def case_eta_minutes_from_point(
    db: Session,
    case: EmergencyCase,
    point: GpsPoint | None,
) -> int | None:
    """Prototype ETA: OSRM routed route when available, else straight-line."""
    routed = route_eta_minutes_from_point(case, point)
    if routed is not None:
        return routed

    hospital = case.hospital
    if hospital is None or hospital.latitude is None or hospital.longitude is None:
        return None
    origin: tuple[float, float] | None = None
    if point is not None:
        origin = (float(point.latitude), float(point.longitude))
    elif case.ambulance is not None and case.ambulance.hospital is not None:
        base = case.ambulance.hospital
        if base.latitude is not None and base.longitude is not None:
            origin = (float(base.latitude), float(base.longitude))
    if origin is None:
        return None
    return eta_minutes(
        origin[0], origin[1], float(hospital.latitude), float(hospital.longitude)
    )


def case_eta_minutes(db: Session, case: EmergencyCase) -> int | None:
    """Prototype ETA (minutes) from the latest fix to the destination hospital."""
    return case_eta_minutes_from_point(db, case, latest_gps(db, case.id))


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
