import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Ambulance
from app.models.enums import AmbulanceStatus, UserRole


def _register(client, role, idx):
    username = f"{role}{idx}"
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "s3curepass",
            "role": role,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, username):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "s3curepass"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_ambulance(paramedic_id):
    db = SessionLocal()
    try:
        ambulance = Ambulance(
            vehicle_number=f"AMB-{uuid.uuid4().hex[:8].upper()}",
            assigned_to_id=paramedic_id,
            status=AmbulanceStatus.available,
        )
        db.add(ambulance)
        db.commit()
        db.refresh(ambulance)
        return ambulance
    finally:
        db.close()


def _make_paramedic(client, idx=0):
    user = _register(client, "paramedic", idx)
    token = _login(client, user["username"])
    return user, token


def _make_admin(client, idx=0):
    user = _register(client, "hospital_admin", idx)
    token = _login(client, user["username"])
    return user, token


def _make_doctor(client, idx=0):
    user = _register(client, "doctor", idx)
    token = _login(client, user["username"])
    return user, token


def _create_hospital(client, token):
    resp = client.post(
        "/api/v1/hospitals",
        headers=_auth(token),
        json={"name": "City General", "city": "Pune", "capabilities": {"icu": True}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_patient(client, token, idx=0):
    resp = client.post(
        "/api/v1/patients",
        headers=_auth(token),
        json={"name": f"Patient {idx}", "age": 34, "sex": "m"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_case(client, token, patient_id, ambulance_id, idx=0, complaint=None):
    resp = client.post(
        "/api/v1/cases",
        headers=_auth(token),
        json={
            "patient_id": str(patient_id),
            "ambulance_id": str(ambulance_id),
            "chief_complaint": complaint or f"Complaint {idx}",
            "severity": "high",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- Hospitals ----


def test_hospital_create_by_admin_201(client: TestClient):
    _, admin_token = _make_admin(client)
    hospital = _create_hospital(client, admin_token)
    uuid.UUID(hospital["id"])
    assert hospital["name"] == "City General"
    assert hospital["city"] == "Pune"


def test_hospital_list_200(client: TestClient):
    _, admin_token = _make_admin(client)
    _create_hospital(client, admin_token)
    _create_hospital(client, admin_token)
    _, doc_token = _make_doctor(client)
    resp = client.get("/api/v1/hospitals", headers=_auth(doc_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_hospital_create_unauthorized_401(client: TestClient):
    resp = client.post(
        "/api/v1/hospitals", json={"name": "X", "city": "Y"}
    )
    assert resp.status_code == 401


def test_hospital_create_wrong_role_403(client: TestClient):
    _, token = _make_doctor(client)
    resp = client.post(
        "/api/v1/hospitals",
        headers=_auth(token),
        json={"name": "X", "city": "Y"},
    )
    assert resp.status_code == 403


# ---- Patients ----


def test_patient_create_by_paramedic_201(client: TestClient):
    user, token = _make_paramedic(client)
    patient = _create_patient(client, token)
    uuid.UUID(patient["id"])
    assert patient["created_by_id"] == user["id"]
    assert patient["name"] == "Patient 0"


def test_patient_get_200(client: TestClient):
    _, token = _make_paramedic(client)
    patient = _create_patient(client, token)
    resp = client.get(f"/api/v1/patients/{patient['id']}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Patient 0"


def test_patient_get_404(client: TestClient):
    _, token = _make_paramedic(client)
    resp = client.get(f"/api/v1/patients/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


def test_patient_create_unauthorized_401(client: TestClient):
    resp = client.post("/api/v1/patients", json={"name": "No Auth"})
    assert resp.status_code == 401


def test_patient_create_wrong_role_403(client: TestClient):
    _, token = _make_doctor(client)
    resp = client.post(
        "/api/v1/patients",
        headers=_auth(token),
        json={"name": "Doctor tries"},
    )
    assert resp.status_code == 403


# ---- Cases ----


def test_case_create_201_linked(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    uuid.UUID(case["id"])
    assert case["patient_id"] == patient["id"]
    assert case["ambulance_id"] == str(ambulance.id)
    assert case["status"] == "active"
    assert case["created_by_id"] == user["id"]


def test_case_wrong_ambulance_403(client: TestClient):
    user1, token1 = _make_paramedic(client, 0)
    _seed_ambulance(user1["id"])
    _, token2 = _make_paramedic(client, 1)
    patient = _create_patient(client, token1)

    ambulance2 = _seed_ambulance(user1["id"])
    resp = client.post(
        "/api/v1/cases",
        headers=_auth(token2),
        json={
            "patient_id": patient["id"],
            "ambulance_id": str(ambulance2.id),
            "severity": "high",
        },
    )
    assert resp.status_code == 403


def test_case_invalid_patient_404(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    resp = client.post(
        "/api/v1/cases",
        headers=_auth(token),
        json={
            "patient_id": str(uuid.uuid4()),
            "ambulance_id": str(ambulance.id),
        },
    )
    assert resp.status_code == 404


def test_case_get_own_200(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    resp = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == case["id"]


def test_case_get_other_403(client: TestClient):
    user, token = _make_paramedic(client, 0)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)

    _, other_token = _make_paramedic(client, 1)
    resp = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(other_token))
    assert resp.status_code == 403


def test_case_list_open_doctor_sees_all(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    _create_case(client, token, patient["id"], ambulance.id)

    _, doc_token = _make_doctor(client)
    resp = client.get("/api/v1/cases", headers=_auth(doc_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp_p = client.get("/api/v1/cases", headers=_auth(token))
    assert resp_p.status_code == 200
    assert len(resp_p.json()) == 1


def test_case_unauthenticated_401(client: TestClient):
    resp = client.get("/api/v1/cases")
    assert resp.status_code == 401


# ---- Vitals ----


def _world(client):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    return user, token, ambulance, patient, case


VITALS_PAYLOAD = {
    "heart_rate": 118,
    "spo2": 91,
    "systolic_bp": 90,
    "diastolic_bp": 60,
    "temperature": 37.2,
    "respiratory_rate": 26,
    "source": "simulated",
}


def test_vital_post_201_and_get(client: TestClient):
    _, token, _, _, case = _world(client)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(token),
        json=VITALS_PAYLOAD,
    )
    assert resp.status_code == 201, resp.text
    vital = resp.json()
    assert vital["case_id"] == case["id"]
    assert vital["heart_rate"] == 118
    assert vital["spo2"] == 91

    history = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token)
    )
    assert history.status_code == 200
    body = history.json()
    assert len(body) == 1
    for key, value in VITALS_PAYLOAD.items():
        assert body[0][key] == value


def test_vital_non_owner_403(client: TestClient):
    _, token, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(other_token),
        json=VITALS_PAYLOAD,
    )
    assert resp.status_code == 403


def test_vital_invalid_case_404(client: TestClient):
    _, token, _, _, _ = _world(client)
    resp = client.post(
        f"/api/v1/cases/{uuid.uuid4()}/vitals",
        headers=_auth(token),
        json=VITALS_PAYLOAD,
    )
    assert resp.status_code == 404


def test_vital_invalid_values_422(client: TestClient):
    _, token, _, _, case = _world(client)
    bad = dict(VITALS_PAYLOAD)
    bad["spo2"] = 150
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(token),
        json=bad,
    )
    assert resp.status_code == 422


def test_vitals_get_by_doctor_200(client: TestClient):
    _, token, _, _, case = _world(client)
    client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(token),
        json=VITALS_PAYLOAD,
    )
    _, doc_token = _make_doctor(client)
    resp = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(doc_token)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_e2e_paramedic_to_vitals(client: TestClient):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    resp = client.post(
        f"/api/v1/cases/{case['id']}/vitals",
        headers=_auth(token),
        json=VITALS_PAYLOAD,
    )
    assert resp.status_code == 201
    history = client.get(
        f"/api/v1/cases/{case['id']}/vitals", headers=_auth(token)
    )
    assert history.status_code == 200
    assert history.json()[0]["heart_rate"] == 118
