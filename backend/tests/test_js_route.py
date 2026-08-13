"""Feature 7: real-time route/map geometry helpers (``vendor/medha/route.js``).

``route.js`` is a DOM-free module (haversine distance, scene offsets, polyline
interpolation, OSRM fetch with straight-line fallback) shared by the ambulance
simulator and the hospital dashboard. A Node harness contract-tests the real
module headlessly, mirroring the ``handover.js`` pattern; the Python side
asserts the structural facts the harness reports. All inputs are synthetic
fixture data.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROUTE_JS_DIR = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "vendor" / "medha"
)
HARNESS = Path(__file__).resolve().parent / "js" / "route_check.cjs"


def _run() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not available")
    result = subprocess.run(
        [node, str(HARNESS), str(ROUTE_JS_DIR)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_haversine_medha_to_ruby():
    out = _run()
    assert 1.0 < out["haversineKm"] < 1.3


def test_offset_and_scene_point_bounds():
    out = _run()
    assert 3.8 < out["offsetKm"] < 4.2
    assert 3.0 <= out["sceneKm"] <= 6.0


def test_straight_route_derives_distance_and_duration():
    out = _run()["straight"]
    assert out["source"] == "straight_line"
    assert 900 < out["distanceM"] < 1400
    assert 100 < out["durationS"] < 300


def test_polyline_interpolation_is_consistent():
    out = _run()
    assert out["cumTailKm"] == pytest.approx(out["pathTotalKm"], abs=1e-9)
    assert 2.8 < out["pathTotalKm"] < 3.3
    assert out["midKm"] == pytest.approx(out["pathTotalKm"] / 2, abs=0.2)
    assert out["interpStart"] == [18.52, 73.85]


def test_build_route_falls_back_to_straight_line_offline():
    out = _run()["fallback"]
    assert out["source"] == "straight_line"
    assert out["coords"] == 2
    assert out["hasOrigin"] is True
    assert out["hasDestination"] is True
    assert out["distanceM"] > 0
    assert out["durationS"] > 0
