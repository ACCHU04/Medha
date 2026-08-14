"""Feature 3: hospital dashboard pre-arrival packet helpers.

``packet.js`` is a DOM-free module (packet construction from live dashboard
state, HTML escaping, compact printable card) so a Node harness can
contract-test the real module headlessly, mirroring ``handover.js``. The
Python side asserts the structural facts the harness reports. All inputs are
synthetic; the packet is a decision-support summary of transportable
monitoring data, not a certified medical record and not a diagnosis.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS_DIR = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "hospital-dashboard"
)
HARNESS = Path(__file__).resolve().parent / "js" / "packet_check.cjs"


def _run() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not available")
    result = subprocess.run(
        [node, str(HARNESS), str(APP_JS_DIR)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_packet_maps_live_state():
    p = _run()["packet"]
    assert p["caseCode"] == "AAAA"
    assert p["patientName"] == "Anita <Sharma> & Co"
    assert p["complaint"] == 'Chest <pain> & "dyspnea"'
    assert p["riskClass"] == "high"
    assert p["score"] == 8
    assert p["sirsMet"] is True
    assert p["severity"] == "high"
    assert p["vitalsCount"] == 1
    assert p["latestHr"] == 122
    assert p["ecgCount"] == 1
    assert p["ecgCaptured"] is True
    assert p["ecgQualityOk"] is True
    assert p["destination"] == "City General"
    assert p["eta"] == 6
    assert p["status"] == "transporting"
    assert p["vehicle"] == "AMB-1234"
    assert p["gpsLive"] is True
    assert p["acceptance"] == "accepted"
    assert p["prepared"] is True
    assert p["preparedAuto"] is True
    assert "not a diagnosis" in p["boundary"]


def test_print_html_contains_sections_and_escapes_input():
    h = _run()["printHtml"]
    assert h["hasBoundary"] is True
    assert h["hasPatient"] is True
    assert h["hasPatientEscaped"] is True
    assert h["hasComplaintEscaped"] is True
    assert h["hasNoRawScript"] is True
    assert h["hasNews2"] is True
    assert h["hasSirs"] is True
    assert h["hasEta"] is True
    assert h["hasGps"] is True
    assert h["hasAccepted"] is True
    assert h["hasSections"] is True


def test_print_html_handles_minimal_case():
    m = _run()["minimal"]
    assert m["caseCode"] == "ZZZZ"
    assert m["hasNoNews2"] is True
    assert m["hasNoVitals"] is True
    assert m["hasNoEcg"] is True
    assert m["hasAwaiting"] is True


def test_build_returns_null_when_case_missing():
    out = _run()["missing"]
    assert out["isNull"] is True
