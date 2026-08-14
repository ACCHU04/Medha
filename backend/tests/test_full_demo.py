"""Full-journey E2E gate (v0.6.0-feature6).

Chains the entire MEDHA LINK scenario against the real API (TestClient) and
the production offline device client (``app.services.sync.device``), exactly as
the ambulance simulator behaves:

    device register -> patient -> case (with GCS + medications) ->
    scene_arrival -> transport_start (nearest hospital + ETA) -> hospital
    accept -> prepare -> online vitals -> deterioration (critical reading,
    latest_risk snapshot) -> offline buffering (device outbox) -> reconnect
    flush + server-side dedupe -> digitized ECG -> FHIR + CDA handover export
    (incl. GCS / medications transport lines) -> hospital_arrival ->
    case_closed -> ambulance freed.

This proves the full Feature 3/4/5/6 chain in one journey rather than repeating
the individual feature tests. Browser-only concerns (canvas rendering, visual
cards/charts, IndexedDB UI state, print layout) are deliberately out of scope
here and are covered by the manual walkthrough instead.
"""

import uuid
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Ambulance, CaseEvent, EcgTracing, GpsPoint, Vital
from app.schemas.sync import SyncOp, SyncPushResponse
from app.services.sync.device import AmbulanceDevice, SQLiteLocalStore, TransportError
from app.services.sync.hlc import HlcClock

from test_ecg import PNG_1X1, QUALITY, WAVEFORM
from test_resources import (
    _auth,
    _make_admin,
    _make_paramedic,
    _seed_ambulance,
)

FHIR = "application/fhir+json"
CDA_NS = "urn:hl7-org:v3"

NORMAL_VITALS = {
    "heart_rate": 82,
    "spo2": 97,
    "systolic_bp": 124,
    "diastolic_bp": 78,
    "temperature": 36.8,
    "respiratory_rate": 16,
    "source": "simulated",
}

CRITICAL_VITALS = {
    "heart_rate": 142,
    "spo2": 84,
    "systolic_bp": 78,
    "diastolic_bp": 48,
    "temperature": 38.9,
    "respiratory_rate": 31,
    "source": "simulated",
}


class ClientTransport:
    """SyncTransport over the FastAPI TestClient (stands in for httpx)."""

    def __init__(self, client, token):
        self._client = client
        self._token = token

    def push(self, batch):
        payload = {"batch": [op.model_dump(mode="json") for op in batch]}
        resp = self._client.post(
            "/api/v1/sync/push", headers=_auth(self._token), json=payload
        )
        if resp.status_code != 200:
            raise TransportError(f"HTTP {resp.status_code}: {resp.text}")
        return SyncPushResponse.model_validate(resp.json())


class ToggleTransport:
    """Flips the device between online and offline without swapping objects.

    Mirrors the simulator's SIMULATE OFFLINE / back-online control.
    """

    def __init__(self, real):
        self._real = real
        self.online = True

    def push(self, batch):
        if not self.online:
            raise TransportError("simulated network loss")
        return self._real.push(batch)


def _hospital(client, token, name, lat, lon):
    resp = client.post(
        "/api/v1/hospitals",
        headers=_auth(token),
        json={
            "name": name,
            "city": "Pune",
            "latitude": lat,
            "longitude": lon,
            "capabilities": {"icu": True},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _transition(client, token, case_id, event_type, **extra):
    resp = client.post(
        f"/api/v1/cases/{case_id}/transitions",
        headers=_auth(token),
        json={"event_type": event_type, **extra},
    )
    assert resp.status_code == 200, f"{event_type}: {resp.text}"
    return resp.json()


def _home_base(ambulance_id, hospital_id):
    db = SessionLocal()
    try:
        ambulance = db.get(Ambulance, ambulance_id)
        ambulance.hospital_id = hospital_id
        db.commit()
    finally:
        db.close()


def _vital_data(case_id, values, timestamp):
    return {"case_id": str(case_id), "timestamp": timestamp, **values}


def test_full_demo_journey(client: TestClient, tmp_path):
    user, token = _make_paramedic(client)
    _, admin_token = _make_admin(client)
    ambulance = _seed_ambulance(user["id"])

    medha = _hospital(client, admin_token, "MEDHA City Hospital", 18.5204, 73.8567)
    _hospital(client, admin_token, "Ruby Hall Clinic", 18.5285, 73.8631)
    _home_base(ambulance.id, medha["id"])

    device = client.post(
        "/api/v1/devices", headers=_auth(token), json={"label": "demo-device"}
    )
    assert device.status_code == 201, device.text
    device_id = device.json()["id"]

    store = SQLiteLocalStore(tmp_path / "outbox.sqlite")
    transport = ToggleTransport(ClientTransport(client, token))
    amb_device = AmbulanceDevice(store, transport, HlcClock(device_id))

    # 1. Patient + case
    patient = client.post(
        "/api/v1/patients",
        headers=_auth(token),
        json={"name": "Demo Patient", "age": 45, "sex": "m"},
    )
    assert patient.status_code == 201, patient.text
    case = client.post(
        "/api/v1/cases",
        headers=_auth(token),
        json={
            "patient_id": patient.json()["id"],
            "ambulance_id": str(ambulance.id),
            "chief_complaint": "Chest pain",
            "severity": "high",
            "gcs": 12,
            "medications": "Aspirin 300 mg PO",
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    assert case.json()["gcs"] == 12
    assert case.json()["medications"] == "Aspirin 300 mg PO"

    # 2. Scene arrival -> transport (auto nearest = MEDHA City Hospital)
    _transition(client, token, case_id, "scene_arrival")
    moved = _transition(client, token, case_id, "transport_start")
    assert moved["case"]["status"] == "transporting"
    assert moved["case"]["hospital_id"] == medha["id"]

    # 3. Hospital accept + prepare
    accept = client.post(
        f"/api/v1/cases/{case_id}/accept",
        headers=_auth(admin_token),
        json={"hospital_id": medha["id"], "note": "ICU ready"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["case"]["acceptance"] == "accepted"
    prepare = client.post(
        f"/api/v1/cases/{case_id}/prepare",
        headers=_auth(admin_token),
        json={"bed_type": "ICU-3", "notes": "trauma team"},
    )
    assert prepare.status_code == 200, prepare.text
    assert prepare.json()["case"]["prepared_at"] is not None

    # 4. GPS -> ETA appears in the queue
    gps_id = str(uuid.uuid4())
    amb_device.record(
        "gps",
        gps_id,
        {
            "case_id": str(case_id),
            "ambulance_id": str(ambulance.id),
            "latitude": 18.5204,
            "longitude": 73.8567,
            "recorded_at": "2026-08-11T10:00:00Z",
        },
    )
    result = amb_device.flush()
    assert result.online and result.synced == [gps_id]

    queue = client.get("/api/v1/cases", headers=_auth(token))
    assert queue.status_code == 200
    row = next(r for r in queue.json() if r["id"] == case_id)
    assert row["eta_minutes"] is not None
    assert row["destination_hospital"]["name"] == "MEDHA City Hospital"

    # 5. Online vitals, then deterioration
    first_vital_id = str(uuid.uuid4())
    first_hlc = amb_device.record(
        "vital", first_vital_id, _vital_data(case_id, NORMAL_VITALS, "2026-08-11T10:01:01Z")
    )
    for minute in range(2):
        amb_device.record(
            "vital",
            str(uuid.uuid4()),
            _vital_data(case_id, NORMAL_VITALS, f"2026-08-11T10:01:0{minute + 2}Z"),
        )
    result = amb_device.flush()
    assert result.online and len(result.synced) == 3

    amb_device.record(
        "vital", str(uuid.uuid4()), _vital_data(case_id, CRITICAL_VITALS, "2026-08-11T10:02:00Z")
    )
    result = amb_device.flush()
    assert result.online and len(result.synced) == 1

    queue = client.get("/api/v1/cases", headers=_auth(token))
    assert queue.status_code == 200
    row = next(r for r in queue.json() if r["id"] == case_id)
    assert row["latest_risk"]["risk_class"] == "high"
    assert row["latest_risk"]["score"] >= 7
    assert row["latest_risk"]["sirs_met"] is True

    # 6. Offline buffering: record 5 vitals while the link is down
    transport.online = False
    for minute in range(5):
        amb_device.record(
            "vital",
            str(uuid.uuid4()),
            _vital_data(case_id, NORMAL_VITALS, f"2026-08-11T10:03:0{minute}Z"),
        )
    offline = amb_device.flush()
    assert offline.online is False
    assert offline.synced == []
    assert amb_device.queue_size() == 5

    # 7. Reconnect: everything flushes, queue drains
    transport.online = True
    online = amb_device.flush()
    assert online.online
    assert len(online.synced) == 5
    assert amb_device.queue_size() == 0

    history = client.get(f"/api/v1/cases/{case_id}/vitals", headers=_auth(token))
    assert history.status_code == 200
    assert len(history.json()) == 9

    # 8. Server-side dedupe: replaying an applied op is skipped
    dup = SyncOp(
        op="upsert",
        entity="vital",
        id=uuid.UUID(first_vital_id),
        device_id=uuid.UUID(device_id),
        hlc=first_hlc,
        data=_vital_data(case_id, NORMAL_VITALS, "2026-08-11T10:01:01Z"),
    )
    dup_resp = client.post(
        "/api/v1/sync/push",
        headers=_auth(token),
        json={"batch": [dup.model_dump(mode="json")]},
    )
    assert dup_resp.status_code == 200, dup_resp.text
    assert dup_resp.json()["applied"] == []
    assert dup_resp.json()["skipped"][0]["reason"] == "duplicate"

    # 9. Digitized ECG via the device outbox
    ecg_id = str(uuid.uuid4())
    amb_device.record(
        "ecg",
        ecg_id,
        {
            "case_id": str(case_id),
            "captured_at": "2026-08-11T10:03:30Z",
            "source": "paper_photo",
            "lead_count": 1,
            "paper_speed": "25",
            "image_original": PNG_1X1,
            "image_normalized": PNG_1X1,
            "waveform": WAVEFORM,
            "quality": QUALITY,
            "notes": None,
        },
    )
    result = amb_device.flush()
    assert result.online and result.synced == [ecg_id]

    ecg_list = client.get(f"/api/v1/cases/{case_id}/ecg", headers=_auth(token))
    assert ecg_list.status_code == 200
    assert len(ecg_list.json()) == 1

    # 10. Handover exports: FHIR R4 document bundle + CDA R2-style XML
    fhir = client.get(
        f"/api/v1/cases/{case_id}/handover",
        params={"format": "fhir"},
        headers=_auth(token),
    )
    assert fhir.status_code == 200, fhir.text
    assert fhir.headers["content-type"] == FHIR
    bundle = fhir.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    resources = {e["resource"]["resourceType"]: e["resource"] for e in bundle["entry"]}
    for kind in (
        "Composition",
        "Patient",
        "Encounter",
        "Practitioner",
        "Observation",
        "DiagnosticReport",
    ):
        assert kind in resources, f"missing {kind}"
    sections = {s["title"]: s for s in resources["Composition"]["section"]}
    assert "Record scope" in sections
    assert "not a certified medical record" in sections["Record scope"]["text"]["div"]
    assert len(sections["Vital signs"]["entry"]) == 9
    assert len(sections["ECG"]["entry"]) == 1
    transport_div = sections["Encounter / Transport"]["text"]["div"]
    assert "GCS: 12" in transport_div
    assert "Medications: Aspirin 300 mg PO" in transport_div

    cda = client.get(
        f"/api/v1/cases/{case_id}/handover",
        params={"format": "cda"},
        headers=_auth(token),
    )
    assert cda.status_code == 200, cda.text
    assert cda.headers["content-type"].startswith("text/xml")
    root = ElementTree.fromstring(cda.text)
    assert root.tag == f"{{{CDA_NS}}}ClinicalDocument"
    section_titles = [
        s.findtext(f"{{{CDA_NS}}}title") for s in root.iter(f"{{{CDA_NS}}}section")
    ]
    for name in ("Record scope", "Encounter / Transport", "Vital signs", "ECG"):
        assert name in section_titles, f"missing CDA section {name}"
    all_text = "\n".join(node.text for node in root.iter() if node.text)
    assert "not a certified medical record" in all_text
    assert "MEDHA City Hospital" in all_text
    assert "GCS: 12" in all_text
    assert "Medications: Aspirin 300 mg PO" in all_text

    # 11. Arrival + close; ambulance returns to available
    arrived = _transition(client, token, case_id, "hospital_arrival")
    assert arrived["case"]["status"] == "at_hospital"
    closed = _transition(client, token, case_id, "case_closed")
    assert closed["case"]["status"] == "closed"
    assert closed["case"]["closed_at"] is not None

    # 12. Persistent state: timeline, freed ambulance, stored records
    db = SessionLocal()
    try:
        amb = db.get(Ambulance, ambulance.id)
        assert amb.status.value == "available"
        events = [
            e.event_type.value
            for e in db.query(CaseEvent)
            .filter_by(case_id=case_id)
            .order_by(CaseEvent.created_at)
        ]
        assert events == [
            "scene_arrival",
            "transport_start",
            "hospital_accept",
            "hospital_prepare",
            "risk_changed",
            "risk_changed",
            "risk_changed",
            "ecg_added",
            "hospital_arrival",
            "case_closed",
        ]
        assert db.query(Vital).filter_by(case_id=case_id).count() == 9
        assert db.query(GpsPoint).filter_by(case_id=case_id).count() == 1
        assert db.query(EcgTracing).filter_by(case_id=case_id).count() == 1
    finally:
        db.close()
