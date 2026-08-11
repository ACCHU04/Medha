import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Ambulance, CaseEvent, EmergencyCase, GpsPoint, User
from app.schemas.sync import SyncOp
from app.services.eta import eta_minutes, haversine_km, nearest_hospital
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_admin,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)


# ---- Coordinates: MEDHA (18.5204, 73.8567), Ruby Hall (18.5285, 73.8631) ----


def _hospital(client, token, name, lat, lon, city="Pune"):
    resp = client.post(
        "/api/v1/hospitals",
        headers=_auth(token),
        json={
            "name": name,
            "city": city,
            "latitude": lat,
            "longitude": lon,
            "capabilities": {"icu": True},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_user_hospital(user_id, hospital_id):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        user.hospital_id = hospital_id
        db.commit()
    finally:
        db.close()


def _world(client: TestClient, coords=True):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    admin, admin_token = _make_admin(client)
    hospitals = {}
    if coords:
        hospitals["medha"] = _hospital(client, admin_token, "MEDHA City Hospital", 18.5204, 73.8567)
        hospitals["ruby"] = _hospital(client, admin_token, "Ruby Hall Clinic", 18.5285, 73.8631)
        _assign_home_base(ambulance.id, hospitals["medha"]["id"])
    return user, token, ambulance, case, admin_token, hospitals


def _assign_home_base(ambulance_id, hospital_id):
    db = SessionLocal()
    try:
        ambulance = db.get(Ambulance, ambulance_id)
        ambulance.hospital_id = hospital_id
        db.commit()
    finally:
        db.close()


def _transition(client, token, case_id, event_type, **extra):
    return client.post(
        f"/api/v1/cases/{case_id}/transitions",
        headers=_auth(token),
        json={"event_type": event_type, **extra},
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


# ---- ETA primitives ----


def test_haversine_and_eta_sane():
    km = haversine_km(18.5204, 73.8567, 18.5204, 73.8567)
    assert km < 0.001
    between = haversine_km(18.5204, 73.8567, 18.5285, 73.8631)
    assert 0.5 < between < 3.0
    minutes = eta_minutes(18.5204, 73.8567, 18.5285, 73.8631)
    assert 1 <= minutes < 30


def test_nearest_hospital_excludes_declined(client: TestClient):
    _, _, _, case, admin_token, hospitals = _world(client)
    db = SessionLocal()
    try:
        stored = db.get(EmergencyCase, case["id"])
        nearest = nearest_hospital(db, stored, exclude_id=hospitals["medha"]["id"])
        assert nearest.id == uuid.UUID(hospitals["ruby"]["id"])
    finally:
        db.close()


# ---- GPS offline sync ----


def test_gps_push_applies_and_broadcasts(client: TestClient):
    user, token, ambulance, case, _, _ = _world(client)
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))

    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        resp = _push(
            client, token, [_gps_op(clock, device["id"], case["id"], ambulance.id, 18.52, 73.85)]
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["applied"]) == 1
        msg = ws.receive_json()
        assert msg["type"] == "gps"
        assert msg["gps"]["latitude"] == 18.52
        assert msg["gps"]["case_id"] == str(case["id"])


def test_gps_push_dedupe_and_rejections(client: TestClient):
    user, token, ambulance, case, _, _ = _world(client)
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    op = _gps_op(clock, device["id"], case["id"], ambulance.id, 18.52, 73.85)

    first = _push(client, token, [op])
    assert len(first.json()["applied"]) == 1

    replay = _push(client, token, [op])
    assert replay.json()["applied"] == []
    assert replay.json()["skipped"][0]["reason"] == "duplicate"

    wrong_ambulance = _gps_op(clock, device["id"], case["id"], uuid.uuid4(), 18.52, 73.85)
    assert _push(client, token, [wrong_ambulance]).json()["skipped"][0]["reason"] == (
        "ambulance does not match case"
    )

    db = SessionLocal()
    try:
        assert db.query(GpsPoint).count() == 1
    finally:
        db.close()


def test_gps_push_skipped_when_case_closed(client: TestClient):
    user, token, ambulance, case, _, _ = _world(client)
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    assert _transition(client, token, case["id"], "case_closed").status_code == 200
    resp = _push(
        client, token, [_gps_op(clock, device["id"], case["id"], ambulance.id, 18.52, 73.85)]
    )
    assert resp.json()["skipped"][0]["reason"] == "case is closed"


def test_pull_changes_excludes_gps(client: TestClient):
    user, token, ambulance, case, _, _ = _world(client)
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    _push(
        client, token, [_gps_op(clock, device["id"], case["id"], ambulance.id, 18.52, 73.85)]
    )
    resp = client.get("/api/v1/sync/changes", headers=_auth(token))
    entities = {c["entity"] for c in resp.json()["changes"]}
    assert "gps" not in entities


# ---- Destination + ETA ----


def test_transport_start_sets_destination(client: TestClient):
    _, token, _, case, _, hospitals = _world(client)
    resp = _transition(
        client, token, case["id"], "transport_start",
        hospital_id=hospitals["ruby"]["id"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case"]["hospital_id"] == hospitals["ruby"]["id"]
    assert body["case"]["destination_hospital"]["name"] == "Ruby Hall Clinic"
    assert body["event"]["payload"]["changes"]["hospital_id"] == {
        "previous": None,
        "incoming": hospitals["ruby"]["id"],
    }


def test_transport_start_auto_assigns_nearest(client: TestClient):
    _, token, _, case, _, hospitals = _world(client)
    resp = _transition(client, token, case["id"], "transport_start")
    assert resp.status_code == 200, resp.text
    assert resp.json()["case"]["hospital_id"] == hospitals["medha"]["id"]


def test_hospital_id_only_on_transport_start(client: TestClient):
    _, token, _, case, _, hospitals = _world(client)
    resp = _transition(
        client, token, case["id"], "scene_arrival",
        hospital_id=hospitals["ruby"]["id"],
    )
    assert resp.status_code == 409
    assert "hospital_id only allowed on transport_start" in resp.json()["detail"]


def test_eta_appears_in_queue_after_gps(client: TestClient):
    user, token, ambulance, case, _, hospitals = _world(client)
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    assert _transition(
        client, token, case["id"], "transport_start",
        hospital_id=hospitals["ruby"]["id"],
    ).status_code == 200
    _push(
        client, token, [_gps_op(clock, device["id"], case["id"], ambulance.id, 18.5204, 73.8567)]
    )

    resp = client.get("/api/v1/cases", headers=_auth(token))
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.json()}
    assert rows[case["id"]]["eta_minutes"] is not None
    assert 1 <= rows[case["id"]]["eta_minutes"] < 30
    assert rows[case["id"]]["destination_hospital"]["name"] == "Ruby Hall Clinic"


# ---- Acceptance lifecycle ----


def _transport(client, token, case_id, hospital_id):
    resp = _transition(client, token, case_id, "transport_start", hospital_id=hospital_id)
    assert resp.status_code == 200, resp.text


def test_paramedic_cannot_accept_403(client: TestClient):
    _, token, _, case, _, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    )
    assert resp.status_code == 403


def test_accept_requires_transport_409(client: TestClient):
    _, _, _, case, admin_token, hospitals = _world(client)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    )
    assert resp.status_code == 409
    assert "not in transport" in resp.json()["detail"]


def test_accept_flow_sets_state_and_broadcasts(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])

    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        resp = client.post(
            f"/api/v1/cases/{case['id']}/accept",
            headers=_auth(admin_token),
            json={"hospital_id": hospitals["ruby"]["id"], "note": "ICU ready"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["case"]["acceptance"] == "accepted"
        assert body["case"]["hospital_id"] == hospitals["ruby"]["id"]
        assert body["event"]["event_type"] == "hospital_accept"
        assert body["event"]["payload"]["hospital_name"] == "Ruby Hall Clinic"

        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["event"]["event_type"] == "hospital_accept"
        assert msg["case"]["acceptance"] == "accepted"


def test_accept_wrong_hospital_scoped_user_403(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    _set_user_hospital(_admin_id(admin_token), hospitals["medha"]["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    )
    assert resp.status_code == 403
    assert "not allowed for this hospital" in resp.json()["detail"]


def _admin_id(admin_token):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == "hospital_admin0").one().id
    finally:
        db.close()


def test_decline_recommends_next_nearest(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/decline",
        headers=_auth(admin_token),
        json={"reason": "no free beds"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case"]["acceptance"] == "declined"
    assert body["case"]["decline_reason"] == "no free beds"
    assert body["case"]["recommended_hospital_id"] == hospitals["ruby"]["id"]
    assert body["event"]["event_type"] == "hospital_decline"
    assert body["event"]["payload"]["recommended_hospital_name"] == "Ruby Hall Clinic"


def test_reaccept_after_decline(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["medha"]["id"])
    assert client.post(
        f"/api/v1/cases/{case['id']}/decline",
        headers=_auth(admin_token),
        json={"reason": "full"},
    ).status_code == 200
    resp = client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["case"]["acceptance"] == "accepted"
    assert resp.json()["case"]["decline_reason"] is None


def test_prepare_requires_accept_409(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3"},
    )
    assert resp.status_code == 409
    assert "must accept" in resp.json()["detail"]


def test_prepare_after_accept_sets_preparation(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    assert client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    ).status_code == 200

    resp = client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3", "team_leader": "Dr. X", "notes": "trauma team"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case"]["prepared_at"] is not None
    assert body["case"]["preparation_notes"]["bed_type"] == "ICU-3"
    assert body["event"]["event_type"] == "hospital_prepare"

    double = client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-4"},
    )
    assert double.status_code == 409
    assert "already prepared" in double.json()["detail"]


def test_acceptance_events_in_timeline(client: TestClient):
    _, token, _, case, admin_token, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    assert client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    ).status_code == 200
    assert client.post(
        f"/api/v1/cases/{case['id']}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3"},
    ).status_code == 200

    resp = client.get(f"/api/v1/cases/{case['id']}/events", headers=_auth(token))
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()]
    assert types == ["transport_start", "hospital_accept", "hospital_prepare"]


def test_doctor_can_accept(client: TestClient):
    _, token, _, case, _, hospitals = _world(client)
    _transport(client, token, case["id"], hospitals["ruby"]["id"])
    _, doc_token = _make_doctor(client)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/accept",
        headers=_auth(doc_token),
        json={"hospital_id": hospitals["ruby"]["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["case"]["acceptance"] == "accepted"
