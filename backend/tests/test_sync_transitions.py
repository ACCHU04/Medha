import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Ambulance, CaseEvent, EmergencyCase
from app.schemas.sync import SyncOp
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_paramedic,
    _seed_ambulance,
)


def _register_device(client: TestClient, token: str):
    resp = client.post("/api/v1/devices", headers=_auth(token), json={"label": "amb-tablet"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, ambulance, device, clock, case


def _transition_op(clock, device_id, case_id, event_type, **extra):
    data = {"case_id": str(case_id), "event_type": event_type}
    data.update(extra)
    return SyncOp(
        op="upsert", entity="transition", id=uuid.uuid4(),
        device_id=device_id, hlc=clock.now(), data=data,
    )


def _push(client: TestClient, token: str, ops: list[SyncOp]):
    return client.post(
        "/api/v1/sync/push",
        headers=_auth(token),
        json={"batch": [op.model_dump(mode="json") for op in ops]},
    )


def _event_types(case_id) -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(CaseEvent).filter_by(case_id=case_id).all()
        return [e.event_type.value for e in rows]
    finally:
        db.close()


def test_sync_transition_applies_status_and_event(client: TestClient):
    _, token, ambulance, device, clock, case = _world(client)
    resp = _push(
        client,
        token,
        [
            _transition_op(clock, device["id"], case["id"], "scene_arrival"),
            _transition_op(clock, device["id"], case["id"], "transport_start"),
            _transition_op(clock, device["id"], case["id"], "hospital_arrival"),
            _transition_op(clock, device["id"], case["id"], "case_closed"),
        ],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["applied"]) == 4
    assert body["skipped"] == []

    db = SessionLocal()
    try:
        stored = db.get(EmergencyCase, case["id"])
        assert stored.status.value == "closed"
        assert stored.closed_at is not None
        assert db.get(Ambulance, ambulance.id).status.value == "available"
        assert _event_types(case["id"]) == [
            "scene_arrival",
            "transport_start",
            "hospital_arrival",
            "case_closed",
        ]
    finally:
        db.close()


def test_sync_transition_idempotent_replay(client: TestClient):
    _, token, ambulance, device, clock, case = _world(client)
    op = _transition_op(clock, device["id"], case["id"], "transport_start")
    first = _push(client, token, [op])
    assert len(first.json()["applied"]) == 1

    second = _push(client, token, [op])
    assert second.json()["applied"] == []
    assert second.json()["skipped"][0]["reason"] == "duplicate"

    db = SessionLocal()
    try:
        assert db.get(EmergencyCase, case["id"]).status.value == "transporting"
        assert db.get(Ambulance, ambulance.id).status.value == "transporting"
        assert _event_types(case["id"]) == ["transport_start"]
    finally:
        db.close()


def test_sync_illegal_transition_skipped(client: TestClient):
    _, token, _, device, clock, case = _world(client)
    op = _transition_op(clock, device["id"], case["id"], "hospital_arrival")
    resp = _push(client, token, [op])
    assert resp.json()["applied"] == []
    assert len(resp.json()["skipped"]) == 1
    assert "not allowed" in resp.json()["skipped"][0]["reason"]

    db = SessionLocal()
    try:
        assert db.get(EmergencyCase, case["id"]).status.value == "active"
    finally:
        db.close()


def test_sync_transition_bad_event_type_skipped(client: TestClient):
    _, token, _, device, clock, case = _world(client)
    op = _transition_op(clock, device["id"], case["id"], "nonsense")
    resp = _push(client, token, [op])
    assert resp.json()["applied"] == []
    assert "event_type" in resp.json()["skipped"][0]["reason"]


def test_sync_transition_dependency_ordering(client: TestClient):
    _, token, ambulance, device, clock, _ = _world(client)
    patient_id, case_id = uuid.uuid4(), uuid.uuid4()
    ops = [
        _transition_op(clock, device["id"], case_id, "transport_start"),
        SyncOp(
            op="upsert", entity="case", id=case_id,
            device_id=device["id"], hlc=clock.now(),
            data={
                "patient_id": str(patient_id),
                "ambulance_id": str(ambulance.id),
                "chief_complaint": "offline lifecycle",
                "severity": "high",
            },
        ),
        SyncOp(
            op="upsert", entity="patient", id=patient_id,
            device_id=device["id"], hlc=clock.now(),
            data={"name": "Offline Patient", "age": 40, "sex": "f"},
        ),
    ]
    resp = _push(client, token, ops)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["applied"]) == 3
    assert body["skipped"] == []

    db = SessionLocal()
    try:
        stored = db.get(EmergencyCase, case_id)
        assert stored is not None
        assert stored.status.value == "transporting"
        assert _event_types(case_id) == ["transport_start"]
    finally:
        db.close()


def test_sync_transition_broadcasts_to_websocket(client: TestClient):
    _, token, _, device, clock, case = _world(client)
    with client.websocket_connect(
        f"/ws/cases/{case['id']}/events", subprotocols=[token]
    ) as ws:
        op = _transition_op(clock, device["id"], case["id"], "transport_start")
        resp = _push(client, token, [op])
        assert len(resp.json()["applied"]) == 1
        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["event"]["event_type"] == "transport_start"
        assert msg["case"]["status"] == "transporting"
