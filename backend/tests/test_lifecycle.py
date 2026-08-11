import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.models import Ambulance, CaseEvent, EmergencyCase

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, ambulance, patient, case


def _transition(client: TestClient, token, case_id, event_type, **extra):
    return client.post(
        f"/api/v1/cases/{case_id}/transitions",
        headers=_auth(token),
        json={"event_type": event_type, **extra},
    )


def _events(client: TestClient, token, case_id):
    return client.get(f"/api/v1/cases/{case_id}/events", headers=_auth(token))


# ---- Happy path lifecycle ----


def test_full_lifecycle_reaches_closed(client: TestClient):
    _, token, ambulance, _, case = _world(client)

    def step(event_type):
        resp = _transition(client, token, case["id"], event_type)
        assert resp.status_code == 200, resp.text
        return resp.json()

    first = step("scene_arrival")
    assert first["case"]["status"] == "active"
    assert first["event"]["event_type"] == "scene_arrival"
    assert first["event"]["payload"]["changes"]["status"] == {
        "previous": "active",
        "incoming": "active",
    }

    second = step("transport_start")
    assert second["case"]["status"] == "transporting"
    assert second["event"]["payload"]["changes"]["status"] == {
        "previous": "active",
        "incoming": "transporting",
    }

    third = step("hospital_arrival")
    assert third["case"]["status"] == "at_hospital"

    fourth = step("case_closed")
    assert fourth["case"]["status"] == "closed"
    assert fourth["case"]["closed_at"] is not None

    db = SessionLocal()
    try:
        amb = db.get(Ambulance, ambulance.id)
        assert amb.status.value == "available"
        events = (
            db.query(CaseEvent)
            .filter_by(case_id=case["id"])
            .order_by(CaseEvent.created_at)
            .all()
        )
        assert [e.event_type.value for e in events] == [
            "scene_arrival",
            "transport_start",
            "hospital_arrival",
            "case_closed",
        ]
    finally:
        db.close()


def test_transport_start_sets_ambulance_transporting(client: TestClient):
    _, token, ambulance, _, case = _world(client)
    resp = _transition(client, token, case["id"], "transport_start")
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Ambulance, ambulance.id).status.value == "transporting"
    finally:
        db.close()


# ---- Illegal / repeated transitions -> 409 ----


def test_hospital_arrival_requires_transport_409(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = _transition(client, token, case["id"], "hospital_arrival")
    assert resp.status_code == 409
    assert "not allowed" in resp.json()["detail"]


def test_transport_start_after_hospital_arrival_409(client: TestClient):
    _, token, _, _, case = _world(client)
    assert _transition(client, token, case["id"], "transport_start").status_code == 200
    assert _transition(client, token, case["id"], "hospital_arrival").status_code == 200
    resp = _transition(client, token, case["id"], "transport_start")
    assert resp.status_code == 409
    assert "not allowed" in resp.json()["detail"]


def test_repeated_scene_arrival_409(client: TestClient):
    _, token, _, _, case = _world(client)
    assert _transition(client, token, case["id"], "scene_arrival").status_code == 200
    resp = _transition(client, token, case["id"], "scene_arrival")
    assert resp.status_code == 409
    assert "already recorded" in resp.json()["detail"]


def test_transition_after_closed_409(client: TestClient):
    _, token, _, _, case = _world(client)
    assert _transition(client, token, case["id"], "case_closed").status_code == 200
    resp = _transition(client, token, case["id"], "scene_arrival")
    assert resp.status_code == 409
    assert "already closed" in resp.json()["detail"]


# ---- Severity audit ----


def test_severity_changed_audit_keeps_status(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = _transition(
        client, token, case["id"], "severity_changed", severity="critical"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case"]["status"] == "active"
    assert body["case"]["severity"] == "critical"
    assert body["event"]["event_type"] == "severity_changed"
    assert body["event"]["payload"]["changes"]["severity"] == {
        "previous": "high",
        "incoming": "critical",
    }


def test_severity_changed_requires_severity_409(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = _transition(client, token, case["id"], "severity_changed")
    assert resp.status_code == 409
    assert "severity required" in resp.json()["detail"]


def test_severity_unchanged_409(client: TestClient):
    _, token, _, _, case = _world(client)
    assert (
        _transition(client, token, case["id"], "severity_changed", severity="critical")
        .status_code
        == 200
    )
    resp = _transition(
        client, token, case["id"], "severity_changed", severity="critical"
    )
    assert resp.status_code == 409
    assert "unchanged" in resp.json()["detail"]


def test_severity_changed_after_closed_409(client: TestClient):
    _, token, _, _, case = _world(client)
    assert _transition(client, token, case["id"], "case_closed").status_code == 200
    resp = _transition(
        client, token, case["id"], "severity_changed", severity="critical"
    )
    assert resp.status_code == 409


# ---- Timeline ----


def test_timeline_ordered_after_lifecycle(client: TestClient):
    _, token, _, _, case = _world(client)
    for event_type in [
        "scene_arrival",
        "transport_start",
        "hospital_arrival",
        "case_closed",
    ]:
        assert _transition(client, token, case["id"], event_type).status_code == 200

    resp = _events(client, token, case["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert [e["event_type"] for e in body] == [
        "scene_arrival",
        "transport_start",
        "hospital_arrival",
        "case_closed",
    ]
    for event in body:
        assert event["case_id"] == case["id"]
        assert event["created_at"]
        assert event["payload"]["changes"]["status"]["incoming"]


def test_timeline_empty_for_fresh_case(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = _events(client, token, case["id"])
    assert resp.status_code == 200
    assert resp.json() == []


# ---- Authorization ----


def test_transition_non_owner_403(client: TestClient):
    _, token, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    resp = _transition(client, other_token, case["id"], "transport_start")
    assert resp.status_code == 403


def test_events_non_owner_403(client: TestClient):
    _, token, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    resp = _events(client, other_token, case["id"])
    assert resp.status_code == 403


def test_doctor_can_advance_case(client: TestClient):
    _, token, _, _, case = _world(client)
    assert _transition(client, token, case["id"], "transport_start").status_code == 200
    _, doc_token = _make_doctor(client)
    resp = _transition(client, doc_token, case["id"], "hospital_arrival")
    assert resp.status_code == 200
    assert resp.json()["case"]["status"] == "at_hospital"


def test_transition_unknown_case_404(client: TestClient):
    _, token, _, _, _ = _world(client)
    resp = _transition(client, token, uuid.uuid4(), "scene_arrival")
    assert resp.status_code == 404


def test_transition_unauthenticated_401(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/transitions",
        json={"event_type": "scene_arrival"},
    )
    assert resp.status_code == 401


# ---- Realtime ----


def test_events_ws_receives_live_transition(client: TestClient):
    _, token, _, _, case = _world(client)
    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        resp = _transition(client, token, case["id"], "scene_arrival")
        assert resp.status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["event"]["event_type"] == "scene_arrival"
        assert msg["case"]["status"] == "active"


def test_events_ws_rejects_non_owner(client: TestClient):
    _, token, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/cases/{case['id']}/events", subprotocols=[other_token]
        ) as ws:
            ws.receive_text()


def test_case_status_does_not_change_on_illegal_transition(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = _transition(client, token, case["id"], "hospital_arrival")
    assert resp.status_code == 409
    db = SessionLocal()
    try:
        stored = db.get(EmergencyCase, case["id"])
        assert stored.status.value == "active"
        assert db.query(CaseEvent).count() == 0
    finally:
        db.close()
