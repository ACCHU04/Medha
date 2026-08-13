"""Cross-language clinical contract: ``clinical.js`` (browser UI) must produce
identical NEWS2-5 + SIRS results to ``app.services.clinical`` (the backend /
handover authority) over a matrix covering totals, per-component scores,
contributor strings with direction, risk-class mapping, SIRS criteria, and
missing-parameter edge cases.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.clinical import compute_news2, compute_sirs

CLINICAL_JS_DIR = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "vendor" / "medha"
)
HARNESS = Path(__file__).resolve().parent / "js" / "clinical_check.cjs"

# (label, vital fields, suspected_infection)
_CASES = [
    ("all missing", {}, None),
    ("normal", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("spec example 7/high", {"heart_rate": 118, "spo2": 92, "systolic_bp": 120, "temperature": 37.2, "respiratory_rate": 26}, False),
    ("single 3 forces medium", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 26}, None),
    ("rr boundaries", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 8}, None),
    ("rr 9-11", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 9}, None),
    ("rr 12-20", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 12}, None),
    ("rr 21-24", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 21}, None),
    ("spo2 91", {"heart_rate": 70, "spo2": 91, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("spo2 93", {"heart_rate": 70, "spo2": 93, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("spo2 95", {"heart_rate": 70, "spo2": 95, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("sbp 90", {"heart_rate": 70, "spo2": 97, "systolic_bp": 90, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("sbp 100", {"heart_rate": 70, "spo2": 97, "systolic_bp": 100, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("sbp 110", {"heart_rate": 70, "spo2": 97, "systolic_bp": 110, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("sbp 220", {"heart_rate": 70, "spo2": 97, "systolic_bp": 220, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("pulse 40", {"heart_rate": 40, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("pulse 50", {"heart_rate": 50, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("pulse 91", {"heart_rate": 91, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("pulse 111", {"heart_rate": 111, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("pulse 131", {"heart_rate": 131, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 16}, None),
    ("temp 35.0", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 35.0, "respiratory_rate": 16}, None),
    ("temp 35.1", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 35.1, "respiratory_rate": 16}, None),
    ("temp 36.0", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 36.0, "respiratory_rate": 16}, None),
    ("temp 36.1", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 36.1, "respiratory_rate": 16}, None),
    ("temp 38.1", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 38.1, "respiratory_rate": 16}, None),
    ("temp 39.1", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 39.1, "respiratory_rate": 16}, None),
    ("medium by score 5", {"heart_rate": 111, "spo2": 97, "systolic_bp": 120, "temperature": 38.5, "respiratory_rate": 22}, None),
    ("high 8", {"heart_rate": 131, "spo2": 91, "systolic_bp": 90, "temperature": 39.1, "respiratory_rate": 26}, None),
    ("low directions only", {"heart_rate": 40, "spo2": 97, "systolic_bp": 120, "temperature": 35.0, "respiratory_rate": 16}, None),
    ("sirs met temp+hr", {"heart_rate": 95, "spo2": 97, "systolic_bp": 120, "temperature": 38.5, "respiratory_rate": 14}, None),
    ("sirs not met", {"heart_rate": 95, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 14}, None),
    ("sirs infection flag", {"heart_rate": 70, "spo2": 97, "systolic_bp": 120, "temperature": 37.0, "respiratory_rate": 14}, True),
    ("sirs all four", {"heart_rate": 95, "spo2": 97, "systolic_bp": 120, "temperature": 38.5, "respiratory_rate": 22}, True),
]


def _py_results():
    out = []
    for _label, vital_fields, suspected in _CASES:
        vital = SimpleNamespace(**vital_fields)
        news2 = compute_news2(vital)
        sirs = compute_sirs(vital, suspected)
        out.append(
            {
                "news2": {
                    "score": news2.score,
                    "risk_class": news2.risk_class,
                    "components": news2.components,
                    "contributors": news2.contributors,
                },
                "sirs": {
                    "met": sirs.met,
                    "criteria_met": sirs.criteria_met,
                    "criteria": sirs.criteria,
                },
            }
        )
    return out


def _js_results():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not available")
    scenario = {
        "cases": [
            {"vital": fields, "suspected_infection": suspected}
            for _label, fields, suspected in _CASES
        ]
    }
    with tempfile.TemporaryDirectory() as tmp:
        scenario_path = Path(tmp) / "scenario.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            [node, str(HARNESS), str(CLINICAL_JS_DIR), str(scenario_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["results"]


def test_js_clinical_matches_python_reference():
    assert _js_results() == _py_results()


def test_python_spot_checks():
    py = {label: result for (label, _f, _s), result in zip(_CASES, _py_results())}
    example = py["spec example 7/high"]
    assert example["news2"] == {
        "score": 7,
        "risk_class": "high",
        "components": {"rr": 3, "spo2": 2, "systolic_bp": 0, "heart_rate": 2, "temperature": 0},
        "contributors": ["RR ↑", "SpO₂ ↓", "Pulse ↑"],
    }
    assert py["single 3 forces medium"]["news2"]["risk_class"] == "medium"
    assert py["normal"]["news2"]["score"] == 0
    assert py["normal"]["news2"]["contributors"] == []
    assert py["normal"]["sirs"]["met"] is False
    assert py["sirs all four"]["sirs"] == {
        "met": True,
        "criteria_met": 4,
        "criteria": {
            "temperature": True,
            "heart_rate": True,
            "respiratory_rate": True,
            "suspected_infection": True,
        },
    }
    assert py["all missing"]["news2"]["score"] == 0
    assert py["all missing"]["sirs"]["criteria_met"] == 0
