"""Feature 5: NABH / FHIR handover record export.

``GET /api/v1/cases/{case_id}/handover`` renders a case's prehospital
monitoring data as an interoperable handover document:
``format=fhir`` (FHIR R4 JSON Bundle, default) or ``format=cda`` (simplified
CDA R2-style XML). Access mirrors the ECG/vitals read path (owner paramedic or
any hospital staff).
"""

import json
import uuid
from xml.etree import ElementTree

from app.services.sync.hlc import HlcClock

from test_ecg import _applied, _ecg_op, _push, _world
from test_resources import (
    VITALS_PAYLOAD,
    _auth,
    _make_doctor,
    _make_paramedic,
)

FHIR = "application/fhir+json"
NS = "urn:hl7-org:v3"


def _vital(client, token, case_id):
    resp = client.post(
        f"/api/v1/cases/{case_id}/vitals",
        headers=_auth(token),
        json=VITALS_PAYLOAD,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ecg(client, token, case, device):
    clock = HlcClock(str(device["id"]))
    _applied(_push(client, token, [_ecg_op(clock, device, case["id"])]))


def _resources(bundle):
    return {entry["resource"]["resourceType"]: entry["resource"] for entry in bundle["entry"]}


def _handover(client, token, case_id, fmt="fhir"):
    return client.get(
        f"/api/v1/cases/{case_id}/handover",
        params={"format": fmt},
        headers=_auth(token),
    )


# ---- FHIR R4 bundle ----


def test_handover_fhir_bundle_structure(client):
    _, token, _, case, device = _world(client)
    vital = _vital(client, token, case["id"])
    _ecg(client, token, case, device)

    resp = _handover(client, token, case["id"])
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == FHIR
    bundle = resp.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    assert bundle["identifier"]["value"] == f"case/{case['id']}"

    resources = _resources(bundle)
    for kind in (
        "Composition",
        "Patient",
        "Encounter",
        "Practitioner",
        "Observation",
        "DiagnosticReport",
    ):
        assert kind in resources, f"missing {kind}"

    composition = resources["Composition"]
    assert composition["title"] == "MEDHA LINK prehospital handover"
    sections = {s["title"]: s for s in composition["section"]}
    assert "Record scope" in sections
    assert "not a certified medical record" in sections["Record scope"]["text"]["div"]
    assert len(sections["Vital signs"]["entry"]) == 1
    assert len(sections["ECG"]["entry"]) == 1

    patient = resources["Patient"]
    assert patient["name"][0]["text"] == "Patient 0"
    assert patient["gender"] == "male"

    observations = [
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "Observation"
    ]
    hr_components = [
        comp
        for obs in observations
        for comp in obs.get("component", [])
        if comp["code"]["coding"][0]["code"] == "8867-4"
    ]
    assert len(hr_components) == 1
    assert hr_components[0]["valueQuantity"]["value"] == 118.0
    assert hr_components[0]["valueQuantity"]["code"] == "1/min"

    report = resources["DiagnosticReport"]
    assert report["code"]["coding"][0]["code"] == "11524-6"
    assert report["status"] == "final"
    full_urls = [entry["fullUrl"] for entry in bundle["entry"]]
    assert report["result"][0] in full_urls


def test_handover_fhir_ecg_waveform_present(client):
    _, token, _, case, device = _world(client)
    _ecg(client, token, case, device)

    bundle = _handover(client, token, case["id"]).json()
    observations = [
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "Observation"
    ]
    ecg_obs = [
        obs
        for obs in observations
        if any(ext["url"].endswith("ecg-waveform-mm") for ext in obs.get("extension", []))
    ]
    assert len(ecg_obs) == 1
    waveform = json.loads(ecg_obs[0]["extension"][0]["valueString"])
    assert waveform["channels"][0]["name"] == "I"
    assert ecg_obs[0]["component"][0]["valueInteger"] == 1


def test_handover_fhir_minimal_case(client):
    _, token, _, case, device = _world(client)
    resp = _handover(client, token, case["id"])
    assert resp.status_code == 200, resp.text
    bundle = resp.json()
    resources = _resources(bundle)
    composition = resources["Composition"]
    sections = {s["title"]: s for s in composition["section"]}
    assert sections["Vital signs"]["entry"] == []
    assert sections["ECG"]["entry"] == []
    assert resources["Encounter"]["status"] == "in-progress"


def test_handover_fhir_access_matrix(client):
    _, token, _, case, device = _world(client)

    _, doc_token = _make_doctor(client)
    resp = _handover(client, doc_token, case["id"])
    assert resp.status_code == 200, resp.text

    _, other_token = _make_paramedic(client, 1)
    resp = _handover(client, other_token, case["id"])
    assert resp.status_code == 403

    resp = client.get(f"/api/v1/cases/{case['id']}/handover")
    assert resp.status_code == 401

    resp = _handover(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


# ---- CDA-style XML ----


def test_handover_cda_well_formed(client):
    _, token, _, case, device = _world(client)
    _vital(client, token, case["id"])
    _ecg(client, token, case, device)

    resp = _handover(client, token, case["id"], fmt="cda")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/xml")

    root = ElementTree.fromstring(resp.text)
    assert root.tag == f"{{{NS}}}ClinicalDocument"

    title = root.find(f"{{{NS}}}title")
    assert title is not None and title.text == "MEDHA LINK prehospital handover"

    paragraphs = [
        node.text
        for node in root.iter(f"{{{NS}}}paragraph")
        if node.text
    ]
    joined = "\n".join(paragraphs)
    assert "Heart rate: 118" in joined
    assert "not a certified medical record" in joined

    all_text = "\n".join(node.text for node in root.iter() if node.text)
    assert "Patient 0" in all_text

    sections = [s.findtext(f"{{{NS}}}title") for s in root.iter(f"{{{NS}}}section")]
    for name in ("Record scope", "Encounter / Transport", "Vital signs", "ECG"):
        assert name in sections, f"missing section {name}"


def test_handover_cda_access(client):
    _, token, _, case, device = _world(client)
    _, other_token = _make_paramedic(client, 1)
    resp = _handover(client, other_token, case["id"], fmt="cda")
    assert resp.status_code == 403


def test_handover_bad_format_400(client):
    _, token, _, case, device = _world(client)
    resp = _handover(client, token, case["id"], fmt="pdf")
    assert resp.status_code == 400
