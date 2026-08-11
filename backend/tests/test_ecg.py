"""Feature 4: digitized paper ECG records.

Write path is offline-first: the ambulance pushes an ``ecg`` entity through
/sync/push (base64 images + waveform JSON). Read path is REST: list/detail/
image for the case. Access mirrors vitals (owner paramedic or any staff).
"""

import base64
import uuid

from app.database import SessionLocal
from app.models import EcgTracing
from app.schemas.sync import SyncOp
from app.services.sync.hlc import HlcClock

from test_resources import (
    _auth,
    _create_case,
    _create_patient,
    _make_doctor,
    _make_paramedic,
    _seed_ambulance,
)

PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
WAVEFORM = {
    "grid": {
        "mm_per_px_x": 8,
        "mm_per_px_y": 8,
        "bounds": {"x": 0, "y": 0, "w": 800, "h": 600},
    },
    "channels": [
        {"name": "I", "sample_mm": 2.0, "points": [[0, 10], [2, 12], [4, 15], [6, 13], [8, 9]]}
    ],
}
QUALITY = {
    "resolution": {"w": 800, "h": 600},
    "blur_score": 2000.0,
    "contrast_score": 50.0,
    "brightness": 200.0,
    "checks_passed": True,
    "warnings": [],
}


def _world(client, idx=0):
    user, token = _make_paramedic(client, idx)
    ambulance = _seed_ambulance(user["id"])
    patient = _create_patient(client, token)
    case = _create_case(client, token, patient["id"], ambulance.id)
    device = client.post(
        "/api/v1/devices", headers=_auth(token), json={"label": "ecg-cam"}
    )
    assert device.status_code == 201, device.text
    device = device.json()
    return user, token, ambulance, case, device


def _ecg_op(clock, device, case_id, **overrides):
    data = {
        "case_id": str(case_id),
        "captured_at": "2026-08-11T10:00:00Z",
        "source": "paper_photo",
        "lead_count": 1,
        "paper_speed": "25",
        "image_original": PNG_1X1,
        "image_normalized": PNG_1X1,
        "waveform": WAVEFORM,
        "quality": QUALITY,
        "notes": None,
    }
    data.update(overrides)
    return SyncOp(
        op="upsert",
        entity="ecg",
        id=uuid.uuid4(),
        device_id=device["id"],
        hlc=clock.now(),
        data=data,
    )


def _push(client, token, ops):
    payload = {"batch": [op.model_dump(mode="json") for op in ops]}
    return client.post("/api/v1/sync/push", headers=_auth(token), json=payload)


def _applied(resp):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["skipped"]) == 0, body["skipped"]
    return body["applied"]


# ---- Write path: offline sync push ----

def test_ecg_push_applies_and_reads_back(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    applied = _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))
    assert applied[0]["entity"] == "ecg"

    listing = client.get(
        f"/api/v1/cases/{case['id']}/ecg", headers=_auth(token)
    )
    assert listing.status_code == 200, listing.text
    records = listing.json()
    assert len(records) == 1
    assert records[0]["waveform"]["channels"][0]["name"] == "I"
    assert records[0]["lead_count"] == 1
    assert records[0]["quality"]["checks_passed"] is True
    assert records[0]["captured_by"] is not None

    detail = client.get(
        f"/api/v1/cases/{case['id']}/ecg/{records[0]['id']}", headers=_auth(token)
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == records[0]["id"]

    image = client.get(
        f"/api/v1/cases/{case['id']}/ecg/{records[0]['id']}/image",
        params={"kind": "original"},
        headers=_auth(token),
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content[:4] == b"\x89PNG"


def test_ecg_push_creates_ecg_added_event(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))

    events = client.get(f"/api/v1/cases/{case['id']}/events", headers=_auth(token))
    assert events.status_code == 200
    types = [e["event_type"] for e in events.json()]
    assert "ecg_added" in types


def test_ecg_push_other_paramedic_skipped(client):
    _, token, _, case, device = _world(client)
    _, other_token = _make_paramedic(client, 1)
    clock = HlcClock(str(device["id"]))
    resp = _push(client, other_token, [_ecg_op(clock, device, case["id"])])
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["applied"]) == 0
    assert body["skipped"][0]["entity"] == "ecg"


def test_ecg_push_unregistered_device_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(uuid.uuid4()))
    resp = _push(client, token, [_ecg_op(clock, device, case["id"])])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert body["skipped"][0]["entity"] == "ecg"


def test_ecg_push_invalid_base64_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    op = _ecg_op(clock, device, case["id"], image_original="not!base64!!")
    resp = _push(client, token, [op])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert "base64" in body["skipped"][0]["reason"]


def test_ecg_push_wrong_magic_bytes_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    blob = base64.b64encode(b"this is definitely not an image").decode()
    op = _ecg_op(clock, device, case["id"], image_original=blob)
    resp = _push(client, token, [op])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert "not a recognized image" in body["skipped"][0]["reason"]


def test_ecg_push_empty_waveform_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    op = _ecg_op(
        clock,
        device,
        case["id"],
        waveform={"grid": None, "channels": []},
    )
    resp = _push(client, token, [op])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert "waveform" in body["skipped"][0]["reason"]


def test_ecg_push_oversized_image_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    big = base64.b64encode(b"0" * (8 * 1024 * 1024 + 1)).decode()
    op = _ecg_op(clock, device, case["id"], image_original=big)
    resp = _push(client, token, [op])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert "exceeds" in body["skipped"][0]["reason"]


def test_ecg_push_duplicate_id_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    op = _ecg_op(clock, device, case["id"])
    _applied(_push(client, token, [op]))
    resp = _push(client, token, [op])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert body["skipped"][0]["reason"] == "duplicate"


def test_ecg_push_closed_case_skipped(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    close = client.post(
        f"/api/v1/cases/{case['id']}/transitions",
        headers=_auth(token),
        json={"event_type": "case_closed"},
    )
    assert close.status_code == 200, close.text
    resp = _push(client, token, [_ecg_op(clock, device, case["id"])])
    body = resp.json()
    assert len(body["applied"]) == 0
    assert body["skipped"][0]["reason"] == "case is closed"


# ---- Read path: REST ----

def test_ecg_read_access_matrix(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))

    _, doc_token = _make_doctor(client)
    resp = client.get(f"/api/v1/cases/{case['id']}/ecg", headers=_auth(doc_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    _, other_token = _make_paramedic(client, 1)
    resp = client.get(f"/api/v1/cases/{case['id']}/ecg", headers=_auth(other_token))
    assert resp.status_code == 403

    resp = client.get(f"/api/v1/cases/{case['id']}/ecg")
    assert resp.status_code == 401


def test_ecg_image_bad_kind_400(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))
    ecg_id = client.get(
        f"/api/v1/cases/{case['id']}/ecg", headers=_auth(token)
    ).json()[0]["id"]
    resp = client.get(
        f"/api/v1/cases/{case['id']}/ecg/{ecg_id}/image",
        params={"kind": "sideview"},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_ecg_image_normalized_missing_404(client):
    _, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    op = _ecg_op(clock, device, case["id"], image_normalized=None)
    _applied(_push(client, token, [op]))
    ecg_id = client.get(
        f"/api/v1/cases/{case['id']}/ecg", headers=_auth(token)
    ).json()[0]["id"]
    resp = client.get(
        f"/api/v1/cases/{case['id']}/ecg/{ecg_id}/image",
        params={"kind": "normalized"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_ecg_stored_as_bytea(client):
    user, token, _, case, device = _world(client)
    clock = HlcClock(str(device["id"]))
    _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))

    db = SessionLocal()
    try:
        stored = db.query(EcgTracing).one()
        assert stored.image_original[:4] == b"\x89PNG"
        assert stored.image_normalized == stored.image_original
        assert stored.waveform["channels"][0]["name"] == "I"
        assert stored.captured_by_id == uuid.UUID(user["id"])
    finally:
        db.close()
