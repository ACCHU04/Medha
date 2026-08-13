"""Feature 5 — geofence-triggered hospital preparation.

GPS fix inside the destination hospital's 5 km radius auto-prepares an
accepted, transporting, not-yet-prepared case. Both ingress paths (REST and
sync) trigger the check; the resulting ``hospital_prepare`` event fans out
over the WebSocket and (for sync ingress) retains ``device_id`` + HLC so it
pulls back to devices.
"""

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CaseEvent, User
from app.models.enums import CaseEventType
from app.schemas.sync import SyncOp
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_admin,
    _make_paramedic,
    _seed_ambulance,
)

# MEDHA City Hospital destination: (18.5204, 73.8567)
AT_HOSPITAL = (18.5204, 73.8567)
INSIDE = (18.5650, 73.8567)  # ~4.9 km -> prepares (exercises <= 5)
OUTSIDE = (18.6100, 73.8567)  # ~9.9 km -> no preparation


def _hospital(client, token, name, lat, lon):
    resp = client.post(
        "/api/v1/hospitals",
        headers=_auth(token),
        json={
            "name": name,
            "city": "Pune",
            "latitude": lat,
            "longitude": lon,
            "capabilities": {"icu": True},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    admin, admin_token = _make_admin(client)
    hospitals = {
        "medha": _hospital(client, admin_token, "MEDHA City Hospital", *AT_HOSPITAL),
        "ruby": _hospital(client, admin_token, "Ruby Hall Clinic", 18.5285, 73.8631),
    }
    return user, token, ambulance, patient, case, admin, admin_token, hospitals


def _transport(client, token, case_id, hospital_id=None):
    resp = client.post(
        f"/api/v1/cases/{case_id}/transitions",
        headers=_auth(token),
        json={
            "event_type": "transport_start",
            "hospital_id": hospital_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _accept(client, admin_token, case_id, hospital_id):
    resp = client.post(
        f"/api/v1/cases/{case_id}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospital_id},
    )
    assert resp.status_code == 200, resp.text


def _manual_prepare(client, admin_token, case_id):
    resp = client.post(
        f"/api/v1/cases/{case_id}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3", "team_leader": "Dr. X"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _gps(client, token, case_id, ambulance_id, lat, lon):
    return client.post(
        f"/api/v1/cases/{case_id}/gps",
        headers=_auth(token),
        json={
            "case_id": str(case_id),
            "ambulance_id": str(ambulance_id),
            "latitude": lat,
            "longitude": lon,
            "recorded_at": "2026-08-11T10:00:00Z",
        },
    )


def _gps_op(clock, device_id, case_id, ambulance_id, lat, lon):
    return SyncOp(
        op="upsert", entity="gps", id=uuid.uuid4(),
        device_id=device_id, hlc=clock.now(),
        data={
            "case_id": str(case_id),
            "ambulance_id": str(ambulance_id),
            "latitude": lat,
            "longitude": lon,
            "recorded_at": "2026-08-11T10:00:00Z",
        },
    )


def _push(client, token, ops):
    payload = {"batch": [op.model_dump(mode="json") for op in ops]}
    return client.post("/api/v1/sync/push", headers=_auth(token), json=payload)


def _register_device(client, token):
    resp = client.post("/api/v1/devices", headers=_auth(token), json={"label": "gps-unit"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _prepare_events(case_id):
    db = SessionLocal()
    try:
        return (
            db.query(CaseEvent)
            .filter_by(
                case_id=case_id, event_type=CaseEventType.hospital_prepare
            )
            .order_by(CaseEvent.created_at)
            .all()
        )
    finally:
        db.close()


def _username(user_id):
    db = SessionLocal()
    try:
        return db.get(User, user_id).username
    finally:
        db.close()


def test_inside_radius_auto_prepares(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    resp = _gps(client, token, case["id"], ambulance.id, *AT_HOSPITAL)
    assert resp.status_code == 201, resp.text

    events = _prepare_events(case["id"])
    assert len(events) == 1
    payload = events[0].payload
    assert payload["auto"] is True
    assert payload["by"] == "geofence"
    assert payload["notes"] == "Auto-prepared by geofence"
    assert payload["bed_type"] is None

    body = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token)).json()
    assert body["prepared_at"] is not None
    assert body["preparation_notes"]["notes"] == "Auto-prepared by geofence"
    assert body["preparation_notes"]["auto"] is True


def test_boundary_inside_prepares(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    assert _gps(client, token, case["id"], ambulance.id, *INSIDE).status_code == 201
    assert len(_prepare_events(case["id"])) == 1


def test_outside_radius_no_preparation(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    assert _gps(client, token, case["id"], ambulance.id, *OUTSIDE).status_code == 201
    assert _prepare_events(case["id"]) == []
    body = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token)).json()
    assert body["prepared_at"] is None


def test_not_accepted_no_preparation(client: TestClient):
    _, token, ambulance, _, case, _, _, _ = _world(client)
    _transport(client, token, case["id"])

    assert _gps(client, token, case["id"], ambulance.id, *AT_HOSPITAL).status_code == 201
    assert _prepare_events(case["id"]) == []


def test_manual_prepare_prevents_auto_duplicate(client: TestClient):
    user, token, ambulance, _, case, admin, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])
    manual = _manual_prepare(client, admin_token, case["id"])
    assert manual["event"]["payload"]["auto"] is False
    assert manual["event"]["payload"]["by"] == _username(admin["id"])

    assert _gps(client, token, case["id"], ambulance.id, *AT_HOSPITAL).status_code == 201

    events = _prepare_events(case["id"])
    assert len(events) == 1
    assert events[0].payload["auto"] is False


def test_repeated_gps_only_one_auto_prepare(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    assert _gps(client, token, case["id"], ambulance.id, *INSIDE).status_code == 201
    assert _gps(client, token, case["id"], ambulance.id, *AT_HOSPITAL).status_code == 201
    assert _gps(client, token, case["id"], ambulance.id, *INSIDE).status_code == 201
    assert len(_prepare_events(case["id"])) == 1


def test_closed_case_no_preparation(client: TestClient):
    _, token, ambulance, _, case, _, _, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    for event_type in ("hospital_arrival", "case_closed"):
        resp = client.post(
            f"/api/v1/cases/{case['id']}/transitions",
            headers=_auth(token),
            json={"event_type": event_type},
        )
        assert resp.status_code == 200, resp.text

    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    push = _push(
        client,
        token,
        [_gps_op(clock, device["id"], case["id"], ambulance.id, *AT_HOSPITAL)],
    )
    assert push.status_code == 200
    assert push.json()["applied"] == []
    assert push.json()["skipped"][0]["reason"] == "case is closed"
    assert _prepare_events(case["id"]) == []


def test_manual_prepare_unchanged(client: TestClient):
    _, token, ambulance, _, case, admin, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3"},
    )
    assert resp.status_code == 200
    payload = resp.json()["event"]["payload"]
    assert payload["auto"] is False
    assert payload["by"] == _username(admin["id"])
    assert "auto" in payload

    double = client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-4"},
    )
    assert double.status_code == 409
    assert "already prepared" in double.json()["detail"]


def test_rest_gps_broadcasts_prepare_event(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        assert _gps(client, token, case["id"], ambulance.id, *AT_HOSPITAL).status_code == 201
        first = ws.receive_json()
        second = ws.receive_json()
    by_type = {m["type"] if "type" in m else "event": m for m in (first, second)}
    assert by_type["gps"]["gps"]["case_id"] == str(case["id"])
    event = by_type["event"]["event"]
    assert event["event_type"] == "hospital_prepare"
    assert event["payload"]["auto"] is True


def test_sync_gps_broadcasts_prepare_event_and_pulls(client: TestClient):
    _, token, ambulance, _, case, _, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    _accept(client, admin_token, case["id"], hospitals["medha"]["id"])

    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    op = _gps_op(clock, device["id"], case["id"], ambulance.id, *AT_HOSPITAL)

    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        push = _push(client, token, [op])
        assert push.status_code == 200, push.text
        assert len(push.json()["applied"]) == 1
        first = ws.receive_json()
        second = ws.receive_json()
    by_type = {m["type"] if "type" in m else "event": m for m in (first, second)}
    event = by_type["event"]["event"]
    assert event["event_type"] == "hospital_prepare"
    assert event["payload"]["auto"] is True
    assert event["device_id"] == device["id"]
    assert event["hlc"] == op.hlc
    assert by_type["gps"]["gps"]["id"] == str(op.id)

    changes = client.get(
        "/api/v1/sync/changes", headers=_auth(token)
    ).json()["changes"]
    pulled = [c for c in changes if c["entity"] == "event"]
    assert any(
        c["id"] == event["id"] and c["hlc"] == op.hlc and c["data"]["event_type"] == "hospital_prepare"
        for c in pulled
    )
