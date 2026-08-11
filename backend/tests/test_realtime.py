import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.models import Ambulance, Vital
from app.models.enums import AmbulanceStatus

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _login,
    _make_admin,
    _make_doctor,
    _make_paramedic,
    _register,
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


def _ws_path(case_id) -> str:
    return f"/ws/cases/{case_id}/vitals"


def _connect(client, token, case_id):
    return client.websocket_connect(_ws_path(case_id), subprotocols=[token])


# ---- Connection ----


def test_ws_valid_jwt_connects(client: TestClient):
    _, _, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    with _connect(client, doc_token, case["id"]) as ws:
        assert ws is not None


def test_ws_missing_token_rejected(client: TestClient):
    _, _, _, _, case = _world(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(_ws_path(case["id"])) as ws:
            pass
    assert exc.value.code == 4401


def test_ws_invalid_token_rejected(client: TestClient):
    _, _, _, _, case = _world(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(client, "not.a.jwt", case["id"]) as ws:
            pass
    assert exc.value.code == 4401


# ---- Authorization ----


def test_ws_token_query_fallback_connects(client: TestClient):
    _, _, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    with client.websocket_connect(
        f"{_ws_path(case['id'])}?token={doc_token}"
    ) as ws:
        assert ws is not None


def test_ws_doctor_allowed(client: TestClient):
    _, _, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    with _connect(client, doc_token, case["id"]) as ws:
        pass


def test_ws_hospital_admin_allowed(client: TestClient):
    _, _, _, _, case = _world(client)
    _, admin_token = _make_admin(client)
    with _connect(client, admin_token, case["id"]) as ws:
        pass


def test_ws_paramedic_own_case_allowed(client: TestClient):
    _, token, _, _, case = _world(client)
    with _connect(client, token, case["id"]) as ws:
        pass


def test_ws_paramedic_other_case_rejected(client: TestClient):
    _, _, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(client, other_token, case["id"]) as ws:
            pass
    assert exc.value.code == 4403


# ---- Broadcast ----


def test_ws_receives_posted_vital_and_persists(client: TestClient):
    _, para_token, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    with _connect(client, doc_token, case["id"]) as ws:
        resp = client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(para_token),
            json=VITALS_NORMAL,
        )
        assert resp.status_code == 201
        event = ws.receive_json()
        for key, value in VITALS_NORMAL.items():
            assert event[key] == value
        assert event["case_id"] == case["id"]

    db = SessionLocal()
    try:
        assert db.query(Vital).filter_by(case_id=case["id"]).count() == 1
    finally:
        db.close()


def test_ws_multiple_subscribers_all_receive(client: TestClient):
    _, para_token, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    _, admin_token = _make_admin(client)

    with _connect(client, doc_token, case["id"]) as doc_ws, _connect(
        client, admin_token, case["id"]
    ) as admin_ws, _connect(client, para_token, case["id"]) as para_ws:
        resp = client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(para_token),
            json=VITALS_NORMAL,
        )
        assert resp.status_code == 201
        for ws in (doc_ws, admin_ws, para_ws):
            event = ws.receive_json()
            assert event["heart_rate"] == 118


# ---- Deterioration ----


def test_ws_deterioration_step_change(client: TestClient):
    _, para_token, _, _, case = _world(client)
    _, doc_token = _make_doctor(client)
    with _connect(client, doc_token, case["id"]) as ws:
        client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(para_token),
            json=VITALS_NORMAL,
        )
        normal = ws.receive_json()
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
        critical = ws.receive_json()
        assert critical["heart_rate"] == 142
        assert critical["spo2"] == 84
        assert critical["systolic_bp"] == 78
        assert critical["diastolic_bp"] == 45
        assert critical["respiratory_rate"] == 30
