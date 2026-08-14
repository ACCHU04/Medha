"""Feature 4: ambulance offline-queue priority grouping.

The ambulance simulator groups its IndexedDB outbox by priority so the crew
can see critical traffic queued for sync: ECG records, encounter transitions
and high-news2 vitals are HIGH; everything else is NORMAL. The grouping lives
in ``app.js`` (``opPriority``) and is contract-tested headlessly through the
same clinical.js module the page loads. All inputs are synthetic.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS_DIR = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "ambulance-simulator"
)
HARNESS = Path(__file__).resolve().parent / "js" / "priority_check.cjs"


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


def test_ecg_and_transition_are_high_priority():
    out = _run()
    assert out["ecg"] == "high"
    assert out["transition"] == "high"


def test_high_news2_vital_is_high_priority():
    out = _run()
    assert out["vitalHigh"] == "high"


def test_normal_vital_and_gps_are_normal_priority():
    out = _run()
    assert out["vitalNormal"] == "normal"
    assert out["gps"] == "normal"


def test_degrades_gracefully_without_clinical_module():
    out = _run()
    assert out["vitalNoClinical"] == "normal"
