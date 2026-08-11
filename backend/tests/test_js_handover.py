"""Feature 6: hospital dashboard handover document helpers.

``handover.js`` is a DOM-free module (export URL/filenames, HTML escaping,
dashboard-state summarization, printable handover document) so a Node harness
can contract-test the real module headlessly, mirroring the ambulance
simulator's ``ecg.js`` pattern. The Python side asserts the structural facts
the harness reports. All inputs are synthetic; the document is transportable
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
HARNESS = Path(__file__).resolve().parent / "js" / "handover_check.cjs"


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


def test_export_urls_and_filenames():
    out = _run()
    assert out["exportUrl"]["fhir"] == "/api/v1/cases/abc-123/handover?format=fhir"
    assert out["exportUrl"]["cda"] == "/api/v1/cases/abc-123/handover?format=cda"
    assert out["filename"]["fhir"] == "medha-ABCD-handover-20260811-093015.json"
    assert out["filename"]["cda"] == "medha-ABCD-handover-20260811-093015.xml"


def test_escaping_handles_all_meta_characters():
    out = _run()["escape"]
    assert out["amp"] == "a &amp; b"
    assert out["lt"] == "&lt;script&gt;"
    assert out["gt"] == "&gt;"
    assert out["quote"] == "&quot;"
    assert out["clean"] == "plain"


def test_summary_maps_dashboard_state():
    s = _run()["summary"]
    assert s["caseCode"] == "AAAA"
    assert s["patientName"] == "Anita <Sharma> & Co"
    assert s["severity"] == "high"
    assert s["status"] == "transporting"
    assert s["eta"] == 7
    assert s["acceptance"] == "accepted"
    assert s["prepared"] is True
    assert s["destination"] == {"name": "City General", "city": "Pune"}
    assert s["ambulance"] == "AMB-1234"
    assert s["timelineLabels"] == ["Scene arrival", "Hospital accepted"]
    assert s["vitalsCount"] == 2
    assert s["seriesLen"] == 2
    assert s["latestHr"] == 122
    assert s["ecgCount"] == 1
    assert s["ecgPointCount"] == 2
    assert s["ecgChecksPassed"] is True


def test_print_html_contains_boundary_and_escapes_input():
    p = _run()["printHtml"]
    assert p["hasBoundary"] is True
    assert p["hasPatient"] is True
    assert p["hasPatientEscaped"] is True
    assert p["hasComplaintEscaped"] is True
    assert p["hasNoRawScript"] is True
    assert p["hasEcgCanvas"] is True
    assert p["hasEta"] is True
    assert p["hasTimeline"] is True
    assert p["hasGenerated"] is True


def test_print_html_handles_empty_case():
    m = _run()["minimal"]
    assert m["caseCode"] == "ZZZZ"
    assert m["hasNoEcg"] is True
    assert m["hasEmptyVitals"] is True
