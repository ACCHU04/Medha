"""Cross-language HLC contract: the browser HlcClock (app.js) must produce
byte-identical canonical strings and ordering to the Python reference
implementation in app.services.sync.hlc.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services.sync.hlc import HlcClock, HlcTimestamp, hlc_cmp

DEVICE_ID = "10000000-0000-4000-8000-000000000001"

APP_JS = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "ambulance-simulator"
    / "app.js"
)
HARNESS = Path(__file__).resolve().parent / "js" / "hlc_check.cjs"

# Deterministic wall-clock / received sequence exercising every HLC branch.
_CALLS = [
    {"wall_ms": 100, "received": None},
    {"wall_ms": 100, "received": None},
    {"wall_ms": 200, "received": None},
    {"wall_ms": 150, "received": None},
    {"wall_ms": 300, "received": None},
    {"wall_ms": 300, "received": None},
    {"wall_ms": 400, "received": "00000000000000000300:000002"},
    {"wall_ms": 50, "received": "00000000000000000999:000007"},
]


def _received_str(value: str | None) -> str | None:
    if value is None:
        return None
    return value + ":" + DEVICE_ID


def _python_output(calls: list[dict]) -> list[str]:
    wall = iter(call["wall_ms"] for call in calls)
    clock = HlcClock(DEVICE_ID, wall_millis=lambda: next(wall))
    out = []
    for call in calls:
        recv = _received_str(call["received"])
        out.append(clock.now(HlcTimestamp.from_string(recv) if recv else None))
    return out


def _js_output(calls: list[dict]) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not available")
    scenario = {
        "device_id": DEVICE_ID,
        "wall": [call["wall_ms"] for call in calls],
        "calls": [{"received": _received_str(call["received"])} for call in calls],
        "order_a": "",
        "order_b": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        scenario_path = Path(tmp) / "scenario.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            [node, str(HARNESS), str(APP_JS.parent), str(scenario_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_js_hlc_matches_python_reference():
    python_out = _python_output(_CALLS)

    scenario = {
        "device_id": DEVICE_ID,
        "wall": [call["wall_ms"] for call in _CALLS],
        "calls": [{"received": _received_str(call["received"])} for call in _CALLS],
        "order_a": python_out[0],
        "order_b": python_out[-1],
    }
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not available")
    with tempfile.TemporaryDirectory() as tmp:
        scenario_path = Path(tmp) / "scenario.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            [node, str(HARNESS), str(APP_JS.parent), str(scenario_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stderr
    js = json.loads(result.stdout)

    assert js["out"] == python_out
    assert js["order"] == hlc_cmp(scenario["order_a"], scenario["order_b"])
    assert js["guardOk"] is True
    assert all(len(value) == 64 for value in python_out)


def test_js_hlc_sorted_ordering_matches_python():
    python_out = _python_output(_CALLS)
    js = _js_output(_CALLS)

    for i in range(len(python_out) - 1):
        assert hlc_cmp(python_out[i], python_out[i + 1]) <= 0
        assert js["out"][i] <= js["out"][i + 1]
    assert sorted(js["out"]) == sorted(python_out)
