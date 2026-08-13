"""Real-time map feature: route persistence, GPS history endpoint, OSRM ETA.

``route_geojson`` is captured on the ``transport_start`` transition (REST and
offline sync path) and replayed to both dashboards; ``GET /cases/{id}/gps``
serves the traveled GPS history so a hospital connecting mid-transport can
reconstruct the route. ETA prefers the OSRM road route and scales remaining
``duration_s`` by the fraction of the polyline already covered.
"""

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Ambulance, EmergencyCase, GpsPoint, Hospital
from app.schemas.sync import SyncOp
from app.services.eta import case_eta_minutes_from_point, route_eta_minutes_from_point
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)

ROUTE = {
    "coordinates": [
        [18.5204, 73.8567],
        [18.5300, 73.8600],
        [18.5400, 73.8660],
    ],
    "distance_m": 3540,
    "duration_s": 1200,
    "source": "osrm",
    "origin": {"latitude": 18.5204, "longitude": 73.8567},
    "destination": {"latitude": 18.54, "longitude": 73.866},
}


def _gps_op(clock, device_id, case_id, ambulance_id, lat, lon, recorded_at):
    return SyncOp(
        op="upsert", entity="gps", id=uuid.uuid4(),
        device_id=device_id, hlc=clock.now(),
        data={
            "case_id": str(case_id),
            "ambulance_id": str(ambulance_id),
            "latitude": lat,
            "longitude": lon,
            "recorded_at": recorded_at,
        },
    )


def _transition_op(clock, device_id, case_id, event_type, **extra):
    data = {"case_id": str(case_id), "event_type": event_type}
    data.update(extra)
    return SyncOp(
        op="upsert", entity="transition", id=uuid.uuid4(),
        device_id=device_id, hlc=clock.now(), data=data,
    )


def _push(client, token, ops):
    payload = {"batch": [op.model_dump(mode="json") for op in ops]}
    return client.post("/api/v1/sync/push", headers=_auth(token), json=payload)


def _world(client, route=None):
    user, token = _make_paramedic(client)
    ambulance = _seed_ambulance(user["id"])
    device = client.post(
        "/api/v1/devices", headers=_auth(token), json={"label": "amb-tablet"}
    ).json()
    clock = HlcClock(str(device["id"]))
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    if route is not None:
        resp = client.post(
            f"/api/v1/cases/{case['id']}/transitions",
            headers=_auth(token),
            json={"event_type": "transport_start", "route": route},
        )
        assert resp.status_code == 200, resp.text
    return user, token, ambulance, device, clock, case


# ---- route_geojson persistence ----


def test_transport_start_route_persisted_and_serialized(client: TestClient):
    _, token, _, _, _, case = _world(client, route=ROUTE)

    stored = client.get(
        f"/api/v1/cases/{case['id']}", headers=_auth(token)
    ).json()
    assert stored["status"] == "transporting"
    assert stored["route_geojson"]["source"] == "osrm"
    assert stored["route_geojson"]["duration_s"] == 1200
    assert stored["route_geojson"]["coordinates"] == ROUTE["coordinates"]

    listed = client.get("/api/v1/cases", headers=_auth(token)).json()
    assert any(c["id"] == case["id"] and c["route_geojson"] for c in listed)

    db = SessionLocal()
    try:
        assert db.get(EmergencyCase, case["id"]).route_geojson == ROUTE
    finally:
        db.close()


def test_transport_start_without_route_leaves_route_null(client: TestClient):
    _, token, _, _, _, case = _world(client)
    assert client.get(
        f"/api/v1/cases/{case['id']}", headers=_auth(token)
    ).json()["route_geojson"] is None


def test_transport_start_route_via_sync_persists(client: TestClient):
    _, token, _, device, clock, case = _world(client)
    resp = _push(
        client,
        token,
        [_transition_op(clock, device["id"], case["id"], "transport_start", route=ROUTE)],
    )
    assert len(resp.json()["applied"]) == 1

    db = SessionLocal()
    try:
        assert db.get(EmergencyCase, case["id"]).route_geojson == ROUTE
    finally:
        db.close()


# ---- GPS history endpoint ----


def test_gps_history_ordered_and_shaped(client: TestClient):
    _, token, ambulance, device, clock, case = _world(client)
    resp = _push(
        client,
        token,
        [
            _gps_op(clock, device["id"], case["id"], ambulance.id, 18.5204, 73.8567, "2026-08-11T10:00:00Z"),
            _gps_op(clock, device["id"], case["id"], ambulance.id, 18.5300, 73.8600, "2026-08-11T10:00:01Z"),
            _gps_op(clock, device["id"], case["id"], ambulance.id, 18.5400, 73.8660, "2026-08-11T10:00:02Z"),
        ],
    )
    assert len(resp.json()["applied"]) == 3

    history = client.get(
        f"/api/v1/cases/{case['id']}/gps", headers=_auth(token)
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert [p["latitude"] for p in body] == [18.5204, 18.53, 18.54]
    assert body[0]["longitude"] == 73.8567
    assert body[0]["case_id"] == str(case["id"])
    assert body[0]["ambulance_id"] == str(ambulance.id)


def test_gps_history_unknown_case_404(client: TestClient):
    _, token, _, _, _, _ = _world(client)
    resp = client.get(
        f"/api/v1/cases/{uuid.uuid4()}/gps", headers=_auth(token)
    )
    assert resp.status_code == 404


def test_gps_history_other_paramedic_403_doctor_200(client: TestClient):
    _, token, _, _, _, case = _world(client)
    _, other_token = _make_paramedic(client, 1)
    resp = client.get(
        f"/api/v1/cases/{case['id']}/gps", headers=_auth(other_token)
    )
    assert resp.status_code == 403

    _, doc_token = _make_doctor(client)
    resp = client.get(
        f"/api/v1/cases/{case['id']}/gps", headers=_auth(doc_token)
    )
    assert resp.status_code == 200


def test_gps_history_unauthenticated_401(client: TestClient):
    _, token, _, _, _, case = _world(client)
    resp = client.get(f"/api/v1/cases/{case['id']}/gps")
    assert resp.status_code == 401


# ---- OSRM-aware ETA ----


def _route_case():
    return EmergencyCase(route_geojson=dict(ROUTE))


def _fix(lat, lon):
    return GpsPoint(
        case_id=uuid.uuid4(), ambulance_id=uuid.uuid4(),
        latitude=lat, longitude=lon,
    )


def test_route_eta_scales_duration_by_traveled_fraction():
    case = _route_case()
    assert route_eta_minutes_from_point(case, _fix(18.5204, 73.8567)) == 20
    assert route_eta_minutes_from_point(case, _fix(18.5400, 73.8660)) == 0
    midpoint = route_eta_minutes_from_point(case, _fix(18.5300, 73.8600))
    assert 5 <= midpoint < 20


def test_route_eta_no_fix_uses_full_duration():
    assert route_eta_minutes_from_point(_route_case(), None) == 20


def test_route_eta_rejects_bad_payloads():
    assert route_eta_minutes_from_point(EmergencyCase(), None) is None
    assert route_eta_minutes_from_point(
        EmergencyCase(route_geojson={"duration_s": 600}), None
    ) is None


def test_case_eta_falls_back_to_straight_line_without_route(client: TestClient):
    _, token, _, _, _, case = _world(client)
    db = SessionLocal()
    try:
        hospital = Hospital(
            name="Coords General", city="Pune",
            latitude=18.5204, longitude=73.8567,
        )
        db.add(hospital)
        db.flush()
        case_row = db.get(EmergencyCase, case["id"])
        case_row.hospital_id = hospital.id
        ambulance = db.get(Ambulance, case["ambulance_id"])
        ambulance.hospital_id = hospital.id
        db.commit()
        result = case_eta_minutes_from_point(db, case_row, None)
    finally:
        db.close()
    assert isinstance(result, int)
    assert result >= 0
