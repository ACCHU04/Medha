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
    _make_admin,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)

VITALS_NORMAL = {
    "heart_rate": 118,
    "spo2": 91,
    "systolic_bp": 90,
    "diastolic_bp": 60,
    "temperature": 37.2,
    "respiratory_rate": 26,
    "source": "simulated",
}

VITALS_CRITICAL = {
    "heart_rate": 142,
    "spo2": 84,
    "systolic_bp": 78,
    "diastolic_bp": 45,
    "temperature": 37.2,
    "respiratory_rate": 30,
    "source": "simulated",
}


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, ambulance, patient, case


def _receive_vital(ws):
    """Skip the risk_changed/event broadcasts that share the case channel."""
    while True:
        msg = ws.receive_json()
        if isinstance(msg, dict) and "heart_rate" in msg:
            return msg


def test_case_list_embeds_patient_and_ambulance(client: TestClient):
    _, _, ambulance, patient, case = _world(client)
    _, admin_token = _make_admin(client)
    resp = client.get("/api/v1/cases", headers=_auth(admin_token))
    assert resp.status_code == 200
    row = next(c for c in resp.json() if c["id"] == case["id"])
    assert row["patient"]["name"] == patient["name"]
    assert row["patient"]["age"] == patient["age"]
    assert row["ambulance"]["vehicle_number"] == ambulance.vehicle_number
    assert row["ambulance"]["status"] == ambulance.status.value


def test_case_get_embeds_details(client: TestClient):
    _, _, ambulance, patient, case = _world(client)
    _, admin_token = _make_admin(client)
    resp = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient"]["id"] == patient["id"]
    assert body["ambulance"]["id"] == str(ambulance.id)
    assert body["ambulance"]["vehicle_number"] == ambulance.vehicle_number


def test_dashboard_auth_matrix(client: TestClient):
    _, _, _, _, _ = _world(client)

    _, admin_token = _make_admin(client)
    admin = client.get("/api/v1/cases", headers=_auth(admin_token))
    assert admin.status_code == 200
    assert len(admin.json()) == 1

    _, doc_token = _make_doctor(client)
    doctor = client.get("/api/v1/cases", headers=_auth(doc_token))
    assert doctor.status_code == 200
    assert len(doctor.json()) == 1

    _, para_token = _make_paramedic(client, 5)
    paramedic = client.get("/api/v1/cases", headers=_auth(para_token))
    assert paramedic.status_code == 200
    assert paramedic.json() == []

    anon = client.get("/api/v1/cases")
    assert anon.status_code == 401


def test_admin_vitals_history_200(client: TestClient):
    _, para_token, _, _, case = _world(client)
    client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(para_token),
        json=VITALS_NORMAL,
    )
    _, admin_token = _make_admin(client)
    resp = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(admin_token)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_case_list_exposes_latest_risk_snapshot(client: TestClient):
    """Acuity snapshot must come from the persisted risk_changed event only,
    never recomputed during case listing."""
    _, para_token, _, _, case = _world(client)
    _, admin_token = _make_admin(client)

    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    row = next(r for r in rows if r["id"] == case["id"])
    assert row["latest_risk"] is None

    client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(para_token),
        json=VITALS_CRITICAL,
    )

    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    row = next(r for r in rows if r["id"] == case["id"])
    snap = row["latest_risk"]
    assert snap is not None
    assert snap["score"] == 12
    assert snap["risk_class"] == "high"
    assert snap["sirs_met"] is True
    assert snap["scoring_version"] == "news2-5-v1"

    body = client.get(
        f"/api/v1/cases/{case['id']}", headers=_auth(admin_token)
    ).json()
    assert body["latest_risk"]["score"] == 12
    assert body["latest_risk"]["risk_class"] == "high"


def test_latest_risk_tracks_newest_event(client: TestClient):
    """The snapshot tracks the newest persisted event: a NEWS2 score change
    (critical 12 -> normal 11) must update the queue snapshot."""
    _, para_token, _, _, case = _world(client)
    _, admin_token = _make_admin(client)

    client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(para_token),
        json=VITALS_CRITICAL,
    )
    client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(para_token),
        json=VITALS_NORMAL,
    )

    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    row = next(r for r in rows if r["id"] == case["id"])
    assert row["latest_risk"]["score"] == 11


def test_ws_admin_receives_normal_then_critical(client: TestClient):
    _, para_token, _, _, case = _world(client)
    _, admin_token = _make_admin(client)

    with client.websocket_connect(
        f"/ws/cases/{case['id']}/vitals", subprotocols=[admin_token]
    ) as ws:
        client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(para_token),
            json=VITALS_NORMAL,
        )
        normal = _receive_vital(ws)
        assert normal["heart_rate"] == 118
        assert normal["spo2"] == 91
        assert normal["systolic_bp"] == 90
        assert normal["diastolic_bp"] == 60
        assert normal["respiratory_rate"] == 26

        client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(para_token),
            json=VITALS_CRITICAL,
        )
        critical = _receive_vital(ws)
        assert critical["heart_rate"] == 142
        assert critical["spo2"] == 84
        assert critical["systolic_bp"] == 78
        assert critical["diastolic_bp"] == 45
        assert critical["respiratory_rate"] == 30


def test_static_serves_dashboard_index(client: TestClient):
    resp = client.get("/hospital-dashboard/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MEDHA" in resp.text
    assert "app.js" in resp.text


def _transition_op(clock, device_id, case_id, event_type):
    return SyncOp(
        op="upsert", entity="transition", id=uuid.uuid4(),
        device_id=device_id, hlc=clock.now(),
        data={"case_id": str(case_id), "event_type": event_type},
    )


def _push_transition(client, token, op):
    resp = client.post(
        "/api/v1/sync/push",
        headers=_auth(token),
        json={"batch": [op.model_dump(mode="json")]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"]


def test_open_case_list_tracks_lifecycle(client: TestClient):
    """Open-case list must include active/transporting/at_hospital cases and
    drop cases only once closed (Feature 2)."""
    _, para_token, ambulance, patient, case = _world(client)
    _, admin_token = _make_admin(client)

    device_resp = client.post(
        "/api/v1/devices", headers=_auth(para_token), json={"label": "amb-tablet"}
    )
    assert device_resp.status_code == 201, device_resp.text
    device = device_resp.json()
    clock = HlcClock(str(device["id"]))

    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    assert any(r["id"] == case["id"] for r in rows)

    _push_transition(
        client, para_token,
        _transition_op(clock, device["id"], case["id"], "transport_start"),
    )
    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    row = next(r for r in rows if r["id"] == case["id"])
    assert row["status"] == "transporting"

    _push_transition(
        client, para_token,
        _transition_op(clock, device["id"], case["id"], "case_closed"),
    )
    rows = client.get("/api/v1/cases", headers=_auth(admin_token)).json()
    assert all(r["id"] != case["id"] for r in rows)
