"""NEWS2-5 + SIRS scoring and the persisted ``risk_changed`` event (freeze
features 2-4): baseline creation, score change within a risk class, SIRS
flip, no-op persistence rule, both ingress paths (REST + sync), and the
payload shape incl. ``scoring_version``.
"""

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CaseEvent, EmergencyCase
from app.schemas.sync import SyncOp
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)

# (heart_rate, spo2, systolic_bp, temperature, respiratory_rate)
NORMAL = {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}
HIGH7 = {"heart_rate": 118, "spo2": 92, "systolic_bp": 120, "temperature": 37.2, "respiratory_rate": 26}
HIGH8 = {"heart_rate": 131, "spo2": 92, "systolic_bp": 120, "temperature": 37.2, "respiratory_rate": 26}
SEPSIS = {"heart_rate": 118, "spo2": 97, "systolic_bp": 120, "temperature": 37.2, "respiratory_rate": 22}


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, case


def _post_vital(client, token, case_id, **fields):
    return client.post(
        f"/api/v1/cases/{case_id}/vitals",
        headers=_auth(token),
        json=dict(fields),
    )


def _risk_events(case_id) -> list[CaseEvent]:
    db = SessionLocal()
    try:
        return list(
            db.query(CaseEvent)
            .filter_by(case_id=case_id)
            .order_by(CaseEvent.created_at, CaseEvent.hlc)
        )
    finally:
        db.close()


def _risk_events_of(case_id) -> list[CaseEvent]:
    return [e for e in _risk_events(case_id) if e.event_type.value == "risk_changed"]


def test_score_zero_for_missing_params(client):
    _, token, case = _world(client)
    resp = _post_vital(client, token, case["id"], source="simulated")
    assert resp.status_code == 201
    events = _risk_events_of(case["id"])
    assert len(events) == 1
    payload = events[0].payload
    assert payload["scoring_version"] == "news2-5-v1"
    assert payload["news2_5"]["previous"] is None
    assert payload["news2_5"]["current"] == {"score": 0, "risk_class": "low"}
    assert payload["news2_5"]["contributors"] == []
    assert payload["sirs"]["previous"] is None
    assert payload["sirs"]["current"] == {"met": False, "criteria_met": 0}


def test_risk_baseline_then_changes_and_noop_rest(client):
    _, token, case = _world(client)
    assert _post_vital(client, token, case["id"], source="simulated", **NORMAL).status_code == 201
    assert _post_vital(client, token, case["id"], source="simulated", **HIGH7).status_code == 201
    assert _post_vital(client, token, case["id"], source="simulated", **HIGH7).status_code == 201
    assert _post_vital(client, token, case["id"], source="simulated", **HIGH8).status_code == 201

    events = _risk_events_of(case["id"])
    assert len(events) == 3

    baseline = events[0].payload
    assert baseline["news2_5"]["previous"] is None
    assert baseline["news2_5"]["current"] == {"score": 0, "risk_class": "low"}
    assert baseline["sirs"]["current"] == {"met": False, "criteria_met": 0}

    jump = events[1].payload
    assert jump["news2_5"]["previous"] == {"score": 0, "risk_class": "low"}
    assert jump["news2_5"]["current"] == {"score": 7, "risk_class": "high"}
    assert jump["news2_5"]["contributors"] == ["RR ↑", "SpO₂ ↓", "Pulse ↑"]
    assert jump["sirs"]["previous"] == {"met": False, "criteria_met": 0}
    assert jump["sirs"]["current"] == {"met": True, "criteria_met": 2}

    # Score change within the same risk class (7 -> 8, both high) persists.
    within = events[2].payload
    assert within["news2_5"]["previous"] == {"score": 7, "risk_class": "high"}
    assert within["news2_5"]["current"] == {"score": 8, "risk_class": "high"}


def test_risk_sirs_flip_persists_rest(client):
    _, token, case = _world(client)
    assert _post_vital(client, token, case["id"], source="simulated", **SEPSIS).status_code == 201
    assert _post_vital(client, token, case["id"], source="simulated", **NORMAL).status_code == 201

    events = _risk_events_of(case["id"])
    assert len(events) == 2
    flip = events[1].payload
    # SEPSIS: HR>90 + RR>20 -> SIRS met; NORMAL -> not met (flip persisted).
    assert flip["sirs"]["previous"] == {"met": True, "criteria_met": 2}
    assert flip["sirs"]["current"] == {"met": False, "criteria_met": 0}
    assert flip["news2_5"]["previous"] == {"score": 4, "risk_class": "low"}
    assert flip["news2_5"]["current"] == {"score": 0, "risk_class": "low"}


def test_risk_suspected_infection_drives_sirs_rest(client):
    _, token, case = _world(client)
    # HR 118 (1 criterion) + infection flag -> met. Without the flag -> not met.
    fields = dict(NORMAL)
    fields["heart_rate"] = 118
    first = _post_vital(client, token, case["id"], source="simulated", suspected_infection=True, **fields)
    assert first.status_code == 201
    second = _post_vital(client, token, case["id"], source="simulated", **fields)
    assert second.status_code == 201

    events = _risk_events_of(case["id"])
    assert len(events) == 2
    assert events[0].payload["sirs"]["current"] == {"met": True, "criteria_met": 2}
    assert events[1].payload["sirs"]["current"] == {"met": False, "criteria_met": 1}


def test_risk_baseline_and_noop_sync(client):
    user, token, _ = _world(client)
    resp = client.post("/api/v1/devices", headers=_auth(token), json={"label": "amb-tablet"})
    device = resp.json()
    clock = HlcClock(str(device["id"]))
    case = _create_case(
        client, token, _create_patient(client, token)["id"],
        _seed_ambulance(user["id"]).id, idx=1,
    )

    def vital_op(**fields):
        data = {"case_id": str(case["id"]), "source": "device"}
        data.update(fields)
        return SyncOp(
            op="upsert", entity="vital", id=uuid.uuid4(),
            device_id=device["id"], hlc=clock.now(), data=data,
        )

    def push(op):
        return client.post(
            "/api/v1/sync/push",
            headers=_auth(token),
            json={"batch": [op.model_dump(mode="json")]},
        )

    r1 = push(vital_op(**NORMAL))
    assert len(r1.json()["applied"]) == 1
    r2 = push(vital_op(**HIGH7))
    assert len(r2.json()["applied"]) == 1
    r3 = push(vital_op(**HIGH7))
    assert len(r3.json()["applied"]) == 1

    events = _risk_events_of(case["id"])
    assert len(events) == 2
    assert events[0].payload["news2_5"]["previous"] is None
    assert events[0].hlc is not None
    assert str(events[0].device_id) == device["id"]
    assert events[1].payload["news2_5"]["previous"] == {"score": 0, "risk_class": "low"}
    assert events[1].payload["news2_5"]["current"] == {"score": 7, "risk_class": "high"}


def test_risk_changed_broadcast_on_websocket(client):
    _, token, case = _world(client)
    _, doc_token = _make_doctor(client)
    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[doc_token]
    ) as ws:
        assert _post_vital(client, token, case["id"], source="simulated", **NORMAL).status_code == 201
        # First broadcast is the raw vital; second is the risk_changed event.
        vital_msg = ws.receive_json()
        assert vital_msg["case_id"] == case["id"]
        event_msg = ws.receive_json()
        assert event_msg["type"] == "event"
        assert event_msg["event"]["event_type"] == "risk_changed"
        assert event_msg["event"]["payload"]["scoring_version"] == "news2-5-v1"


def test_risk_event_honors_hlc_from_sync_vital(client):
    user, token, _ = _world(client)
    resp = client.post("/api/v1/devices", headers=_auth(token), json={"label": "amb-tablet"})
    device = resp.json()
    clock = HlcClock(str(device["id"]))
    case = _create_case(
        client, token, _create_patient(client, token)["id"],
        _seed_ambulance(user["id"]).id, idx=2,
    )
    data = {"case_id": str(case["id"]), "source": "device", **NORMAL}
    op = SyncOp(
        op="upsert", entity="vital", id=uuid.uuid4(),
        device_id=device["id"], hlc=clock.now(), data=data,
    )
    client.post(
        "/api/v1/sync/push",
        headers=_auth(token),
        json={"batch": [op.model_dump(mode="json")]},
    )
    events = _risk_events_of(case["id"])
    assert len(events) == 1
    assert events[0].hlc == op.hlc
    assert str(events[0].device_id) == device["id"]
