from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Ambulance, Hospital, User
from app.models.enums import AmbulanceStatus, UserRole
from app.seed_dev import seed_dev

from test_resources import (
    _auth,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
    _create_patient,
    _create_case,
)


def _counts():
    db = SessionLocal()
    try:
        return {
            "users": db.query(User).count(),
            "hospitals": db.query(Hospital).count(),
            "ambulances": db.query(Ambulance).count(),
        }
    finally:
        db.close()


def test_seed_idempotent(client: TestClient):
    first = seed_dev()
    assert first["users"] == ["paramedic1", "doctor1", "admin1"]
    assert first["hospital"] == [
        "MEDHA City Hospital",
        "Ruby Hall Clinic",
        "Jehangir Hospital",
    ]
    assert first["ambulance"] == ["MH-01-AMB-001"]

    second = seed_dev()
    assert not any(second.values())
    assert _counts() == {"users": 3, "hospitals": 3, "ambulances": 1}

    db = SessionLocal()
    try:
        paramedic = db.scalar(
            select(User).where(User.username == "paramedic1")
        )
        assert paramedic.role == UserRole.paramedic
        ambulance = db.scalar(
            select(Ambulance).where(Ambulance.vehicle_number == "MH-01-AMB-001")
        )
        assert ambulance.assigned_to_id == paramedic.id
        assert ambulance.status == AmbulanceStatus.transporting
        assert ambulance.hospital_id is not None
    finally:
        db.close()


def test_seed_users_have_hashed_passwords(client: TestClient):
    seed_dev()
    db = SessionLocal()
    try:
        paramedic = db.scalar(
            select(User).where(User.username == "paramedic1")
        )
        assert paramedic.password_hash != "s3curepass"
        assert paramedic.password_hash.startswith("$2")
    finally:
        db.close()


def test_simulator_workflow_login_to_vitals(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)

    walked = [
        {"heart_rate": 118, "spo2": 91, "systolic_bp": 90, "diastolic_bp": 60,
         "temperature": 37.2, "respiratory_rate": 26, "source": "simulated"},
        {"heart_rate": 120, "spo2": 90, "systolic_bp": 92, "diastolic_bp": 61,
         "temperature": 37.1, "respiratory_rate": 27, "source": "simulated"},
        {"heart_rate": 117, "spo2": 91, "systolic_bp": 89, "diastolic_bp": 60,
         "temperature": 37.3, "respiratory_rate": 26, "source": "simulated"},
    ]
    for vital in walked:
        resp = client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(token),
            json=vital,
        )
        assert resp.status_code == 201, resp.text

    history = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token)
    )
    assert history.status_code == 200
    body = history.json()
    assert len(body) == 3
    by_hr = {row["heart_rate"]: row for row in body}
    for sent in walked:
        row = by_hr[sent["heart_rate"]]
        for key, value in sent.items():
            assert row[key] == value


def test_deterioration_normal_then_critical_persist(client: TestClient):
    _, token, _, _, case = _world(client)
    normal = {
        "heart_rate": 118, "spo2": 91, "systolic_bp": 90, "diastolic_bp": 60,
        "temperature": 37.2, "respiratory_rate": 26, "source": "simulated",
    }
    critical = {
        "heart_rate": 142, "spo2": 84, "systolic_bp": 78, "diastolic_bp": 45,
        "temperature": 37.2, "respiratory_rate": 30, "source": "simulated",
    }
    for payload in (normal, critical):
        resp = client.post(
            f"/api/v1/cases/{case['id']}/vitals",
            headers=_auth(token),
            json=payload,
        )
        assert resp.status_code == 201, resp.text

    history = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token)
    ).json()
    assert len(history) == 2
    rows = {row["heart_rate"]: row for row in history}
    assert rows[118]["spo2"] == 91
    assert rows[118]["systolic_bp"] == 90
    assert rows[118]["diastolic_bp"] == 60
    assert rows[118]["respiratory_rate"] == 26
    assert rows[142]["spo2"] == 84
    assert rows[142]["systolic_bp"] == 78
    assert rows[142]["diastolic_bp"] == 45
    assert rows[142]["respiratory_rate"] == 30


def _world(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, ambulance, patient, case


def test_static_serves_simulator_index(client: TestClient):
    resp = client.get("/ambulance-simulator/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MEDHA" in resp.text
    assert "app.js" in resp.text
