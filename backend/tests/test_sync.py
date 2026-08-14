import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CaseEvent, EmergencyCase, Patient, Vital
from app.schemas.sync import SyncOp
from app.services.sync.hlc import HlcClock, HlcTimestamp

from test_resources import (
    VITALS_PAYLOAD,
    _auth,
    _create_case,
    _create_patient,
    _make_admin,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)


def _register_device(client: TestClient, token: str, label: str = "amb-tablet"):
    resp = client.post("/api/v1/devices", headers=_auth(token), json={"label": label})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    device = _register_device(client, token)
    clock = HlcClock(str(device["id"]))
    return user, token, ambulance, device, clock


def _vital_data(case_id, **overrides):
    data = dict(VITALS_PAYLOAD)
    data["case_id"] = str(case_id)
    data["source"] = "device"
    data.update(overrides)
    return data


def _offline_batch(clock, ambulance_id, device_id):
    patient_id, case_id = uuid.uuid4(), uuid.uuid4()
    vital_id, event_id = uuid.uuid4(), uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=patient_id,
            device_id=device_id, hlc=clock.now(),
            data={"name": "Offline Patient", "age": 40, "sex": "f"},
        ),
        SyncOp(
            op="upsert", entity="case", id=case_id,
            device_id=device_id, hlc=clock.now(),
            data={
                "patient_id": str(patient_id),
                "ambulance_id": str(ambulance_id),
                "chief_complaint": "sync complaint",
                "severity": "high",
            },
        ),
        SyncOp(
            op="upsert", entity="vital", id=vital_id,
            device_id=device_id, hlc=clock.now(),
            data=_vital_data(case_id, heart_rate=118),
        ),
        SyncOp(
            op="upsert", entity="event", id=event_id,
            device_id=device_id, hlc=clock.now(),
            data={
                "case_id": str(case_id),
                "event_type": "scene_arrival",
                "payload": {"note": "on scene"},
            },
        ),
    ]
    return ops, patient_id, case_id, vital_id, event_id


def _push(client: TestClient, token: str, ops: list[SyncOp]):
    payload = {"batch": [op.model_dump(mode="json") for op in ops]}
    return client.post("/api/v1/sync/push", headers=_auth(token), json=payload)


# ---- Devices ----


def test_device_register_returns_uuid(client: TestClient):
    _, token, _, device, _ = _world(client)
    uuid.UUID(str(device["id"]))
    assert device["label"] == "amb-tablet"


def test_device_register_requires_paramedic(client: TestClient):
    _, doc_token = _make_doctor(client)
    resp = client.post("/api/v1/devices", headers=_auth(doc_token), json={"label": "x"})
    assert resp.status_code == 403


# ---- Push: happy path ----


def test_push_offline_batch_creates_all(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    resp = _push(client, token, ops)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["applied"]) == 4
    assert body["skipped"] == []

    db = SessionLocal()
    try:
        assert db.get(Patient, pid) is not None
        case = db.get(EmergencyCase, cid)
        assert case is not None
        assert case.status.value == "active"
        assert case.created_by_id is not None
        assert case.hlc is not None
        assert db.get(Vital, vid) is not None
        event = db.get(CaseEvent, eid)
        assert event is not None
        assert event.event_type.value == "scene_arrival"
        assert event.hlc is not None
    finally:
        db.close()


def test_push_idempotent_replay(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    first = _push(client, token, ops)
    assert len(first.json()["applied"]) == 4

    second = _push(client, token, ops)
    body = second.json()
    assert body["applied"] == []
    assert len(body["skipped"]) == 4

    db = SessionLocal()
    try:
        assert db.query(Patient).count() == 1
        assert db.query(EmergencyCase).count() == 1
        assert db.query(Vital).count() == 1
        # scene_arrival + the risk_changed baseline from the vital snapshot.
        assert db.query(CaseEvent).count() == 2
        assert (
            db.query(CaseEvent).filter_by(event_type="risk_changed").count() == 1
        )
    finally:
        db.close()


def test_push_parent_child_order_independent(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, *_ = _offline_batch(clock, ambulance.id, device["id"])
    shuffled = [ops[1], ops[3], ops[0], ops[2]]
    resp = _push(client, token, shuffled)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["applied"]) == 4


# ---- Push: isolation ----


def test_one_invalid_op_does_not_poison_batch(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, _, eid = _offline_batch(clock, ambulance.id, device["id"])
    bad = SyncOp(
        op="upsert", entity="vital", id=uuid.uuid4(),
        device_id=device["id"], hlc=clock.now(),
        data=_vital_data(cid, spo2=150),
    )
    resp = _push(client, token, ops + [bad])
    body = resp.json()
    assert len(body["applied"]) == 4
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["id"] == str(bad.id)
    assert "validation" in body["skipped"][0]["reason"]

    db = SessionLocal()
    try:
        assert db.get(Patient, pid) is not None
        assert db.get(EmergencyCase, cid) is not None
        assert db.get(CaseEvent, eid) is not None
        assert db.get(Vital, bad.id) is None
    finally:
        db.close()


def test_invalid_event_type_skipped(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    bad = SyncOp(
        op="upsert", entity="event", id=uuid.uuid4(),
        device_id=device["id"], hlc=clock.now(),
        data={"case_id": str(cid), "event_type": "nonsense", "payload": {}},
    )
    resp = _push(client, token, ops + [bad])
    body = resp.json()
    assert body["skipped"][0]["entity"] == "event"
    assert "event_type" in body["skipped"][0]["reason"]


# ---- Push: HLC conflict resolution ----


def test_lww_case_update_wins_with_audit(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    assert len(_push(client, token, ops).json()["applied"]) == 4

    update = SyncOp(
        op="upsert", entity="case", id=cid,
        device_id=device["id"], hlc=clock.now(),
        data={
            "patient_id": str(pid),
            "ambulance_id": str(ambulance.id),
            "severity": "critical",
            "chief_complaint": "sync complaint",
        },
    )
    resp = _push(client, token, [update])
    assert len(resp.json()["applied"]) == 1

    db = SessionLocal()
    try:
        case = db.get(EmergencyCase, cid)
        assert case.severity.value == "critical"
        audits = db.query(CaseEvent).filter_by(case_id=cid).all()
        severity_events = [e for e in audits if e.event_type.value == "severity_changed"]
        assert len(severity_events) == 1
        changes = severity_events[0].payload["changes"]
        assert changes["severity"]["previous"] == "high"
        assert changes["severity"]["incoming"] == "critical"
    finally:
        db.close()


def test_older_hlc_skipped(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    assert len(_push(client, token, ops).json()["applied"]) == 4

    older_hlc = HlcTimestamp(1, 0, str(device["id"])).to_string()
    stale = SyncOp(
        op="upsert", entity="case", id=cid,
        device_id=device["id"], hlc=older_hlc,
        data={
            "patient_id": str(pid),
            "ambulance_id": str(ambulance.id),
            "severity": "low",
        },
    )
    resp = _push(client, token, [stale])
    body = resp.json()
    assert body["applied"] == []
    assert "older or duplicate" in body["skipped"][0]["reason"]

    db = SessionLocal()
    try:
        assert db.get(EmergencyCase, cid).severity.value == "high"
    finally:
        db.close()


def test_sync_case_round_trips_structured_fields(client: TestClient):
    """Offline case create + update carry gcs/medications through the outbox."""
    _, token, ambulance, device, clock = _world(client)
    pid, cid = uuid.uuid4(), uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=pid,
            device_id=device["id"], hlc=clock.now(),
            data={"name": "Offline GCS", "age": 40, "sex": "f"},
        ),
        SyncOp(
            op="upsert", entity="case", id=cid,
            device_id=device["id"], hlc=clock.now(),
            data={
                "patient_id": str(pid),
                "ambulance_id": str(ambulance.id),
                "chief_complaint": "sync structured",
                "severity": "high",
                "gcs": 9,
                "medications": "Oxygen 15 L/min",
            },
        ),
    ]
    assert len(_push(client, token, ops).json()["applied"]) == 2

    db = SessionLocal()
    try:
        case = db.get(EmergencyCase, cid)
        assert case.gcs == 9
        assert case.medications == "Oxygen 15 L/min"
    finally:
        db.close()

    # HLC-newer update changes the structured fields with an audit event.
    update = SyncOp(
        op="upsert", entity="case", id=cid,
        device_id=device["id"], hlc=clock.now(),
        data={
            "patient_id": str(pid),
            "ambulance_id": str(ambulance.id),
            "severity": "high",
            "chief_complaint": "sync structured",
            "gcs": 14,
            "medications": "GTN 400 mcg SL",
        },
    )
    assert len(_push(client, token, [update]).json()["applied"]) == 1

    db = SessionLocal()
    try:
        case = db.get(EmergencyCase, cid)
        assert case.gcs == 14
        assert case.medications == "GTN 400 mcg SL"
        audits = db.query(CaseEvent).filter_by(case_id=cid).all()
        updates = [
            e for e in audits if e.event_type.value == "state_updated"
            and "gcs" in e.payload.get("changes", {})
        ]
        assert len(updates) == 1
        assert updates[0].payload["changes"]["gcs"] == {
            "previous": 9, "incoming": 14,
        }
    finally:
        db.close()


def test_sync_rejects_invalid_gcs(client: TestClient):
    """GCS must be an integer in 3..15; out-of-range is rejected."""
    _, token, ambulance, device, clock = _world(client)
    pid = uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=pid,
            device_id=device["id"], hlc=clock.now(),
            data={"name": "Bad GCS", "age": 40, "sex": "m"},
        ),
        SyncOp(
            op="upsert", entity="case", id=uuid.uuid4(),
            device_id=device["id"], hlc=clock.now(),
            data={
                "patient_id": str(pid),
                "ambulance_id": str(ambulance.id),
                "severity": "high",
                "gcs": 2,
            },
        ),
    ]
    resp = _push(client, token, ops)
    body = resp.json()
    assert len(body["applied"]) == 1
    assert body["skipped"][0]["entity"] == "case"
    assert "invalid gcs" in body["skipped"][0]["reason"]


def test_vital_dedupe_by_id(client: TestClient):
    _, token, ambulance, device, clock = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock, ambulance.id, device["id"])
    assert len(_push(client, token, ops).json()["applied"]) == 4

    replay = SyncOp(
        op="upsert", entity="vital", id=vid,
        device_id=device["id"], hlc=clock.now(),
        data=_vital_data(cid, heart_rate=200),
    )
    resp = _push(client, token, [replay])
    body = resp.json()
    assert body["applied"] == []
    assert body["skipped"][0]["reason"] == "duplicate"

    db = SessionLocal()
    try:
        assert db.query(Vital).filter_by(case_id=cid).count() == 1
        assert db.query(Vital).filter_by(id=vid).first().heart_rate == 118
    finally:
        db.close()


# ---- Push: authorization ----


def test_push_wrong_paramedic_skipped(client: TestClient):
    _, token_a, ambulance, device_a, clock_a = _world(client)
    ops, _, cid, _, _ = _offline_batch(clock_a, ambulance.id, device_a["id"])
    assert len(_push(client, token_a, ops).json()["applied"]) == 4

    _, token_b = _make_paramedic(client, 1)
    device_b = _register_device(client, token_b, "other-tablet")
    clock_b = HlcClock(str(device_b["id"]))
    intruder = SyncOp(
        op="upsert", entity="vital", id=uuid.uuid4(),
        device_id=device_b["id"], hlc=clock_b.now(),
        data=_vital_data(cid, heart_rate=99),
    )
    resp = _push(client, token_b, [intruder])
    body = resp.json()
    assert body["applied"] == []
    assert "not authorized for this case" in body["skipped"][0]["reason"]

    db = SessionLocal()
    try:
        assert db.query(Vital).filter_by(case_id=cid).count() == 1
    finally:
        db.close()


def test_push_unassigned_ambulance_skipped(client: TestClient):
    _, token_a, ambulance, _, _ = _world(client)
    _, token_b = _make_paramedic(client, 1)
    device_b = _register_device(client, token_b, "other-tablet")
    clock_b = HlcClock(str(device_b["id"]))

    pid, cid = uuid.uuid4(), uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=pid,
            device_id=device_b["id"], hlc=clock_b.now(),
            data={"name": "B Patient", "age": 30, "sex": "m"},
        ),
        SyncOp(
            op="upsert", entity="case", id=cid,
            device_id=device_b["id"], hlc=clock_b.now(),
            data={
                "patient_id": str(pid),
                "ambulance_id": str(ambulance.id),
                "severity": "moderate",
            },
        ),
    ]
    resp = _push(client, token_b, ops)
    body = resp.json()
    applied_entities = {a["entity"] for a in body["applied"]}
    assert applied_entities == {"patient"}
    assert len(body["skipped"]) == 1
    assert "not assigned to this ambulance" in body["skipped"][0]["reason"]


def test_push_unowned_device_skipped(client: TestClient):
    _, token_a, _, device_a, _ = _world(client)
    _, token_b = _make_paramedic(client, 1)

    pid = uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=pid,
            device_id=device_a["id"], hlc=HlcClock(str(device_a["id"])).now(),
            data={"name": "Impostor", "age": 20, "sex": "f"},
        ),
    ]
    resp = _push(client, token_b, ops)
    body = resp.json()
    assert body["applied"] == []
    assert "device not registered" in body["skipped"][0]["reason"]


def test_push_hlc_device_mismatch_skipped(client: TestClient):
    _, token_a, _, device_a, _ = _world(client)
    _, token_b = _make_paramedic(client, 1)
    device_b = _register_device(client, token_b, "other-tablet")

    clock_b = HlcClock(str(device_b["id"]))
    pid = uuid.uuid4()
    ops = [
        SyncOp(
            op="upsert", entity="patient", id=pid,
            device_id=device_a["id"], hlc=clock_b.now(),
            data={"name": "Mismatch", "age": 20, "sex": "f"},
        ),
    ]
    # device_a is owned by token_a; the hlc embeds device_b -> mismatch
    resp = _push(client, token_a, ops)
    body = resp.json()
    assert body["applied"] == []
    assert "hlc device does not match" in body["skipped"][0]["reason"]


def test_push_requires_paramedic(client: TestClient):
    _, doc_token = _make_doctor(client)
    resp = client.post(
        "/api/v1/sync/push", headers=_auth(doc_token), json={"batch": []}
    )
    assert resp.status_code == 403


# ---- Push: realtime bridge ----


def test_push_broadcasts_vital_to_websocket(client: TestClient):
    _, token_a, ambulance, device_a, clock_a = _world(client)
    ops, _, cid, _, _ = _offline_batch(clock_a, ambulance.id, device_a["id"])
    assert len(_push(client, token_a, ops).json()["applied"]) == 4

    _, doc_token = _make_doctor(client)
    with client.websocket_connect(
        f"/ws/cases/{cid}/vitals", subprotocols=[doc_token]
    ) as ws:
        vital = SyncOp(
            op="upsert", entity="vital", id=uuid.uuid4(),
            device_id=device_a["id"], hlc=clock_a.now(),
            data=_vital_data(cid, heart_rate=142, spo2=84),
        )
        resp = _push(client, token_a, [vital])
        assert len(resp.json()["applied"]) == 1
        event = ws.receive_json()
        assert event["heart_rate"] == 142
        assert event["spo2"] == 84
        assert event["case_id"] == str(cid)


# ---- Pull ----


def test_pull_returns_batch_and_case_filter(client: TestClient):
    _, token_a, ambulance, device_a, clock_a = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock_a, ambulance.id, device_a["id"])
    assert len(_push(client, token_a, ops).json()["applied"]) == 4

    _, doc_token = _make_doctor(client)
    resp = client.get("/api/v1/sync/changes", headers=_auth(doc_token))
    assert resp.status_code == 200
    changes = resp.json()["changes"]
    entities = {c["entity"] for c in changes}
    assert entities == {"patient", "case", "vital", "event"}

    filtered = client.get(
        f"/api/v1/sync/changes?case_id={cid}", headers=_auth(doc_token)
    ).json()["changes"]
    assert {c["entity"] for c in filtered} == {"patient", "case", "vital", "event"}


def test_pull_since_cursor(client: TestClient):
    _, token_a, ambulance, device_a, clock_a = _world(client)
    ops, pid, cid, vid, eid = _offline_batch(clock_a, ambulance.id, device_a["id"])
    assert len(_push(client, token_a, ops).json()["applied"]) == 4

    case_hlc = ops[1].hlc
    _, doc_token = _make_doctor(client)
    resp = client.get(
        f"/api/v1/sync/changes?since={case_hlc}", headers=_auth(doc_token)
    )
    changes = resp.json()["changes"]
    assert {c["entity"] for c in changes} == {"vital", "event"}
    for change in changes:
        assert change["hlc"] > case_hlc


def test_pull_paramedic_isolated(client: TestClient):
    _, token_a, ambulance, device_a, clock_a = _world(client)
    ops_a, *_ = _offline_batch(clock_a, ambulance.id, device_a["id"])
    assert len(_push(client, token_a, ops_a).json()["applied"]) == 4

    user_b, token_b = _make_paramedic(client, 1)
    ambulance_b = _seed_ambulance(user_b["id"])
    device_b = _register_device(client, token_b, "tablet-b")
    clock_b = HlcClock(str(device_b["id"]))
    ops_b, *_ = _offline_batch(clock_b, ambulance_b.id, device_b["id"])
    assert len(_push(client, token_b, ops_b).json()["applied"]) == 4

    seen_a = client.get("/api/v1/sync/changes", headers=_auth(token_a)).json()["changes"]
    seen_b = client.get("/api/v1/sync/changes", headers=_auth(token_b)).json()["changes"]
    # 4 ops + the risk_changed baseline event each batch now syncs to devices.
    assert len(seen_a) == 5
    assert len(seen_b) == 5
    ids_a = {c["id"] for c in seen_a}
    ids_b = {c["id"] for c in seen_b}
    assert ids_a.isdisjoint(ids_b)


def test_pull_requires_auth(client: TestClient):
    resp = client.get("/api/v1/sync/changes")
    assert resp.status_code == 401


# ---- REST backward compatibility ----


def test_rest_vital_client_id_and_device_stored(client: TestClient):
    _, token, ambulance, device, _ = _world(client)
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)

    vital_id = uuid.uuid4()
    payload = dict(VITALS_PAYLOAD)
    payload["id"] = str(vital_id)
    payload["device_id"] = str(device["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token), json=payload
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == str(vital_id)

    db = SessionLocal()
    try:
        vital = db.get(Vital, vital_id)
        assert vital is not None
        assert str(vital.device_id) == str(device["id"])
    finally:
        db.close()


def test_rest_vital_unowned_device_403(client: TestClient):
    _, token, ambulance, _, _ = _world(client)
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)

    _, other_token = _make_paramedic(client, 1)
    other_device = _register_device(client, other_token, "other-tablet")

    payload = dict(VITALS_PAYLOAD)
    payload["device_id"] = str(other_device["id"])
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token), json=payload
    )
    assert resp.status_code == 403


def test_rest_patient_client_id_stored(client: TestClient):
    _, token, _, _, _ = _world(client)
    patient_id = uuid.uuid4()
    resp = client.post(
        "/api/v1/patients",
        headers=_auth(token),
        json={"id": str(patient_id), "name": "Client ID Patient", "age": 45, "sex": "m"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == str(patient_id)
