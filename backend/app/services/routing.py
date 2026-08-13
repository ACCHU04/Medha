"""Specialty-aware hospital routing (freeze feature 1).

Upgrades the distance-only ``nearest_hospital`` into a capability-aware
recommendation: filter candidate hospitals whose ``capabilities`` (JSONB
boolean tags) contain a capability matched from the chief complaint, then
sort by great-circle distance. Falls back to distance-only when no hospital
matches, so a recommendation is always produced when any hospital has
coordinates.

Call sites (both previously used ``nearest_hospital``):
- ``case_lifecycle.apply_transition`` on ``transport_start`` fallback
- ``case.decline_case`` for the recommended hospital after a decline
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EmergencyCase, Hospital
from .eta import haversine_km, latest_position

# (keywords matched on the lower-cased chief complaint, capability tag)
_COMPLAINT_CAPABILITIES: list[tuple[list[str], str]] = [
    (["chest pain", "cardiac", "heart", "angina", "mi", "palpitation"], "cardiology"),
    (["trauma", "rta", "fall", "crash", "accident", "fracture", "burn"], "trauma"),
    (
        ["labour", "pregnancy", "maternity", "delivery", "obstetric", "eclampsia"],
        "maternity",
    ),
    (["child", "pediatric", "infant", "baby", "neonat"], "pediatric"),
]
DEFAULT_CAPABILITY = "general"

MAX_ALTERNATIVES = 2


def required_capabilities(chief_complaint: str | None) -> list[str]:
    """Capability tags a hospital should have for this complaint.

    Specialty complaints require the specialty tag; everything else requires
    ``general``. A hospital with no matching tag is only ever chosen through
    the distance-only fallback (never a wrong-specialty win over a match).
    """
    if not chief_complaint:
        return [DEFAULT_CAPABILITY]
    text = chief_complaint.lower()
    for keywords, tag in _COMPLAINT_CAPABILITIES:
        if any(k in text for k in keywords):
            return [tag]
    return [DEFAULT_CAPABILITY]


def _hospital_capability_tags(capabilities: dict | None) -> set[str]:
    if not isinstance(capabilities, dict):
        return set()
    return {key for key, value in capabilities.items() if value}


@dataclass
class Recommendation:
    """A recommended destination with the reason behind it."""

    hospital: Hospital
    matched_capabilities: list[str]
    distance_km: float
    alternatives: list[tuple[Hospital, float]]


def recommend_hospital(
    db: Session,
    case: EmergencyCase,
    *,
    exclude_id: UUID | None = None,
    origin: tuple[float, float] | None = None,
) -> Recommendation | None:
    """Best hospital for this case: capability match first, then distance.

    ``origin`` defaults to the latest GPS fix, falling back to the ambulance's
    home base (same semantics as the ETA helpers). Returns ``None`` when no
    hospital with coordinates exists (or when no origin can be derived).
    """
    required = required_capabilities(case.chief_complaint)
    if origin is None:
        origin = latest_position(db, case)
    if origin is None:
        return None
    lat0, lon0 = origin

    stmt = select(Hospital).where(
        Hospital.latitude.isnot(None), Hospital.longitude.isnot(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(Hospital.id != exclude_id)

    scored: list[tuple[Hospital, float, list[str]]] = []
    for hospital in db.scalars(stmt):
        km = haversine_km(
            lat0, lon0, float(hospital.latitude), float(hospital.longitude)
        )
        tags = _hospital_capability_tags(hospital.capabilities)
        matched = [cap for cap in required if cap in tags]
        scored.append((hospital, km, matched))

    if not scored:
        return None

    matching = sorted((s for s in scored if s[2]), key=lambda s: s[1])
    others = sorted((s for s in scored if not s[2]), key=lambda s: s[1])
    if matching:
        best_hospital, best_km, best_matched = matching[0]
        pool = matching[1:] + others
    else:
        best_hospital, best_km, best_matched = others[0]
        pool = others[1:]

    alternatives = [(h, km) for h, km, _ in pool[:MAX_ALTERNATIVES]]
    return Recommendation(best_hospital, best_matched, best_km, alternatives)
