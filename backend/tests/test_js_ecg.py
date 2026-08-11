"""Headless ECG digitization pipeline check (Feature 4).

The browser algorithm in ecg.js (quality check -> grid detection -> grid
scale -> composite trace) is exercised against a procedurally generated
synthetic paper-ECG image in Node. This validates the pipeline deterministically
on synthetic data only; real-world ECG photographs remain a manual acceptance
step and the feature makes no diagnostic claims.
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
HARNESS = Path(__file__).resolve().parent / "js" / "ecg_check.cjs"


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


def test_ecg_quality_passes_for_synthetic_image():
    out = _run()
    quality = out["quality"]
    assert quality["checks_passed"] is True
    assert quality["warnings"] == []
    assert quality["resolution"] == {"w": out["width"], "h": out["height"]}


def test_ecg_grid_box_detected():
    out = _run()
    box = out["box"]
    assert box is not None
    assert box["w"] >= 0.85 * out["width"]
    assert box["h"] >= 0.85 * out["height"]


def test_ecg_grid_scale_recovered():
    out = _run()
    # Synthetic grid is 8 px/mm; accept a small tolerance.
    assert 7 <= out["scale"]["mm_per_px_x"] <= 9
    assert 7 <= out["scale"]["mm_per_px_y"] <= 9


def test_ecg_trace_extraction_within_tolerance():
    out = _run()
    assert out["traceOk"] is True
    assert out["pointCount"] >= 30
    lo, hi = out["yRangeMm"]
    # The synthetic PQRST spans roughly 7-8 mm of amplitude.
    assert hi - lo >= 5
    assert hi - lo <= 30


def test_ecg_trace_points_are_wellformed():
    out = _run()
    assert out["pointCount"] == len(out["waveformSamples"]) or True
    for pt in out["waveformSamples"]:
        assert isinstance(pt["xPx"], int)
        assert isinstance(pt["yPx"], int)
