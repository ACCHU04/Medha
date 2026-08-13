"""Specialty-aware hospital routing (freeze feature 1).

``recommend_hospital`` prefers a hospital whose ``capabilities`` match the
chief complaint before falling back to plain distance. This module tests the
mapping, the scoring order, the no-match fallback, the exclusion rule, and the
integration points (``transport_start`` fallback and ``decline``
recommendation) plus the ``CaseOut.recommendation`` 'why this hospital?' payload.
"""

from decimal import Decimal

from app.database import SessionLocal
from app.models import GpsPoint, Hospital
from app.services.routing import (
    MAX_ALTERNATIVES,
    DEFAULT_CAPABILITY,
    recommend_hospital,
    required_capabilities,
)
from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_admin,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)

ORIGIN = (18.51, 73.86)

# (name, lat, lon, capabilities)
HOSPITALS = [
    ("Medha Cardiology", 18.54, 73.86, {"cardiology": True, "icu": True}),
    ("City General", 18.50, 73.85, {"general": True, "icu": True}),
    ("Ruby Trauma", 18.55, 73.87, {"trauma": True, "icu": True}),
]


def _seed_hospitals(capabilities_list=None):
    specs = capabilities_list or HOSPITALS
    db = SessionLocal()
    try:
        hospitals = []
        for name, lat, lon, caps in specs:
            hospital = Hospital(
                name=name,
                city="Pune",
                latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)),
                capabilities=caps,
            )
            db.add(hospital)
            hospitals.append(hospital)
        db.commit()
        for hospital in hospitals:
            db.refresh(hospital)
        return {h.name: h for h in hospitals}
    finally:
        db.close()


def _make_case_with_origin(client, token, ambulance_id, complaint):
    patient = _create_patient(client, token)
    case = _create_case(
        client, token, patient["id"], ambulance_id, idx=0
    )
    _seed_gps(client, token, case["id"], str(ambulance_id), *ORIGIN)
    return case


def _seed_gps(client, token, case_id, ambulance_id, lat, lon):
    resp = client.post(
        f"/api/v1/cases/{case_id}/gps",
        headers=_auth(token),
        json={
            "case_id": case_id,
            "ambulance_id": ambulance_id,
            "latitude": lat,
            "longitude": lon,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- required_capabilities mapping ----


def test_required_capabilities_mapping():
    assert required_capabilities("Chest pain and shortness of breath") == [
        "cardiology"
    ]
    assert required_capabilities("RTA with fracture") == ["trauma"]
    assert required_capabilities("labour pain") == ["maternity"]
    assert required_capabilities("child fever") == ["pediatric"]
    assert required_capabilities("fever and cough") == [DEFAULT_CAPABILITY]
    assert required_capabilities(None) == [DEFAULT_CAPABILITY]
    assert required_capabilities("") == [DEFAULT_CAPABILITY]


# ---- recommend_hospital core ----


def test_recommend_prefers_capability_match_over_distance():
    _seed_hospitals()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        case = _stub_case(db, "chest pain")
        rec = recommend_hospital(db, case, origin=ORIGIN)
        assert rec is not None
        # City General is nearer, but Medha Cardiology is the only cardiology
        # hospital and therefore wins despite being farther.
        assert rec.hospital.name == "Medha Cardiology"
        assert rec.matched_capabilities == ["cardiology"]
        assert rec.alternatives[0][0].name == "City General"
    finally:
        db.close()


def test_recommend_no_match_falls_back_to_nearest():
    specs = [
        ("Cardio A", 18.55, 73.85, {"cardiology": True}),
        ("Trauma B", 18.45, 73.95, {"trauma": True}),
    ]
    _seed_hospitals(specs)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        case = _stub_case(db, "fever and cough")  # only general required
        rec = recommend_hospital(db, case, origin=ORIGIN)
        assert rec is not None
        # No hospital matches -> nearest hospital wins (Cardio A is closer to origin).
        assert rec.hospital.name == "Cardio A"
        assert rec.matched_capabilities == []
    finally:
        db.close()


def test_recommend_exclude_id():
    _seed_hospitals()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        case = _stub_case(db, "chest pain")
        excluded = db.query(Hospital).filter_by(name="Medha Cardiology").one()
        rec = recommend_hospital(db, case, origin=ORIGIN, exclude_id=excluded.id)
        assert rec is not None
        assert rec.hospital.id != excluded.id
        # No other cardiology hospital -> distance fallback to the nearest.
        assert rec.hospital.name == "City General"
    finally:
        db.close()


def test_recommend_none_without_origin_or_hospitals(client):
    # No hospitals seeded and a fresh case has no GPS origin -> None.
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    from app.database import SessionLocal
    from app.models import EmergencyCase

    db = SessionLocal()
    try:
        orm = db.get(EmergencyCase, uuid.UUID(case["id"]))
        assert recommend_hospital(db, orm) is None
    finally:
        db.close()


def test_recommend_alternatives_bounded():
    _seed_hospitals()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        case = _stub_case(db, "chest pain")
        rec = recommend_hospital(db, case, origin=ORIGIN)
        assert len(rec.alternatives) == 2
        assert len(rec.alternatives) <= MAX_ALTERNATIVES
    finally:
        db.close()


def _stub_case(db, complaint):
    from app.models import EmergencyCase
    from app.models.enums import CaseStatus

    case = EmergencyCase(
        patient_id=_any_uuid(),
        ambulance_id=_any_uuid(),
        chief_complaint=complaint,
        status=CaseStatus.active,
    )
    return case


import uuid


def _any_uuid():
    return uuid.uuid4()


# ---- Integration: transport_start fallback ----


def test_transport_start_fallback_picks_specialty_hospital(client):
    _seed_hospitals()
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id, complaint="Chest pain")
    _seed_gps(client, token, case["id"], str(ambulance.id), *ORIGIN)

    resp = client.post(
        f"/api/v1/cases/{case['id']}/transitions",
        headers=_auth(token),
        json={"event_type": "transport_start"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case"]["status"] == "transporting"
    dest = body["case"]["destination_hospital"]
    assert dest["name"] == "Medha Cardiology", dest


# ---- Integration: decline recommendation + 'why this hospital?' ----


def test_decline_sets_specialty_recommendation(client):
    _seed_hospitals()
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id, complaint="Chest pain")
    _seed_gps(client, token, case["id"], str(ambulance.id), *ORIGIN)

    # Transport starts at the specialty hospital (Medha Cardiology).
    resp = client.post(
        f"/api/v1/cases/{case['id']}/transitions",
        headers=_auth(token),
        json={"event_type": "transport_start"},
    )
    assert resp.status_code == 200, resp.text
    transport = resp.json()["case"]
    assert transport["destination_hospital"]["name"] == "Medha Cardiology"

    # Now a doctor declines -> recommendation should offer the next best.
    _, doc_token = _make_doctor(client)
    declined = client.post(
        f"/api/v1/cases/{case['id']}/decline",
        headers=_auth(doc_token),
        json={"reason": "no beds"},
    )
    assert declined.status_code == 200, declined.text
    body = declined.json()["case"]
    assert body["acceptance"] == "declined"
    assert body["recommended_hospital_id"] is not None
    assert body["recommended_hospital"]["name"] != "Medha Cardiology"
    rec = body["recommendation"]
    assert rec is not None
    assert rec["hospital"]["id"] == body["recommended_hospital_id"]
    assert rec["alternatives"] and rec["alternatives"][0]["hospital"]["id"] != rec["hospital"]["id"]


def test_recommendation_present_pre_transport(client):
    _seed_hospitals()
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id, complaint="Chest pain")
    _seed_gps(client, token, case["id"], str(ambulance.id), *ORIGIN)

    resp = client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendation"] is not None
    assert body["recommendation"]["hospital"]["name"] == "Medha Cardiology"
    assert "cardiology" in body["recommendation"]["matched_capabilities"]
