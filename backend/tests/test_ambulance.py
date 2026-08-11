import uuid

from fastapi.testclient import TestClient

from test_resources import (
    _auth,
    _login,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)


def test_ambulance_mine_paramedic_200(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    resp = client.get("/api/v1/ambulances/mine", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(ambulance.id)
    assert body["vehicle_number"] == ambulance.vehicle_number
    assert body["assigned_to_id"] == user["id"]
    assert body["status"] == ambulance.status.value


def test_ambulance_mine_no_assignment_404(client: TestClient):
    _, token = _make_paramedic(client)
    resp = client.get("/api/v1/ambulances/mine", headers=_auth(token))
    assert resp.status_code == 404


def test_ambulance_mine_wrong_role_403(client: TestClient):
    _, token = _make_doctor(client)
    resp = client.get("/api/v1/ambulances/mine", headers=_auth(token))
    assert resp.status_code == 403


def test_ambulance_mine_unauthenticated_401(client: TestClient):
    resp = client.get("/api/v1/ambulances/mine")
    assert resp.status_code == 401
