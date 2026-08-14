"""Persisted ``risk_changed`` events (freeze feature 4).

Every vital ingress (REST or sync) computes the NEWS2-5 + SIRS snapshot for
that observation and compares it against the last persisted snapshot for the
case. An event is persisted only on a *meaningful transition*:
- the first computed state after monitoring starts (baseline), or
- a NEWS2-5 total score change (even within the same risk class), or
- a SIRS state flip (met <-> not met).

Unchanged snapshots persist nothing, so the timeline never floods with a
risk event per vital.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CaseEvent, EmergencyCase, Vital
from ..models.enums import CaseEventType
from ..models.user import utcnow
from .clinical import SCORING_VERSION, compute_news2, compute_sirs


def _latest_risk_event(db: Session, case_id: UUID) -> CaseEvent | None:
    events = latest_risk_event_by_case(db, [case_id])
    return events.get(case_id)


def latest_risk_event_by_case(
    db: Session, case_ids: list[UUID]
) -> dict[UUID, CaseEvent]:
    """One query for the newest ``risk_changed`` event per case (DISTINCT ON
    in Postgres). The event's payload is the single source of truth for the
    queue's acuity snapshot — risk is never recomputed at read time."""
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseEvent)
        .where(
            CaseEvent.case_id.in_(case_ids),
            CaseEvent.event_type == CaseEventType.risk_changed,
        )
        .distinct(CaseEvent.case_id)
        .order_by(
            CaseEvent.case_id,
            CaseEvent.hlc.desc().nullslast(),
            CaseEvent.created_at.desc(),
            CaseEvent.id.desc(),
        )
    ).scalars()
    return {event.case_id: event for event in rows}


def _news2_snapshot(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    current = payload.get("news2_5", {}).get("current")
    return current if isinstance(current, dict) else None


def _sirs_snapshot(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    current = payload.get("sirs", {}).get("current")
    return current if isinstance(current, dict) else None


def risk_snapshot(payload: dict | None) -> dict | None:
    """The persisted NEWS2-5 + SIRS snapshot as exposed to the hospital queue.

    Derived only from a persisted ``risk_changed`` event payload; never
    recalculated during case listing.
    """
    if payload is None:
        return None
    news2 = _news2_snapshot(payload)
    if news2 is None:
        return None
    sirs = _sirs_snapshot(payload)
    return {
        "score": news2.get("score"),
        "risk_class": news2.get("risk_class"),
        "sirs_met": bool(sirs.get("met")) if sirs is not None else False,
        "scoring_version": payload.get("scoring_version"),
    }


def evaluate_and_persist_risk(
    db: Session,
    case: EmergencyCase,
    vital: Vital,
    suspected_infection: bool | None = None,
) -> CaseEvent | None:
    """Evaluate this vital against the last snapshot and persist on change.

    Returns the new ``risk_changed`` event, or ``None`` when nothing changed.
    The caller commits (the REST route and the sync savepoint both do).
    """
    news2 = compute_news2(vital)
    sirs = compute_sirs(vital, suspected_infection)

    previous = _latest_risk_event(db, case.id)
    prev_news2 = _news2_snapshot(previous.payload) if previous is not None else None
    prev_sirs = _sirs_snapshot(previous.payload) if previous is not None else None

    news2_changed = prev_news2 is None or news2.score != prev_news2.get("score")
    sirs_changed = prev_sirs is None or sirs.met != prev_sirs.get("met")
    if not (news2_changed or sirs_changed):
        return None

    event = CaseEvent(
        case_id=case.id,
        event_type=CaseEventType.risk_changed,
        payload={
            "scoring_version": SCORING_VERSION,
            "news2_5": {
                "previous": prev_news2,
                "current": {"score": news2.score, "risk_class": news2.risk_class},
                "contributors": news2.contributors,
            },
            "sirs": {
                "previous": prev_sirs,
                "current": {"met": sirs.met, "criteria_met": sirs.criteria_met},
            },
        },
        device_id=vital.device_id,
        hlc=vital.hlc,
        created_at=utcnow(),
    )
    db.add(event)
    return event
