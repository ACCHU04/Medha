"""Synthetic ECG sample variants (Feature 4 closeout).

The ambulance simulator ships a LOAD SAMPLE feature so the offline demo needs
no camera or uploaded photo. ecg-samples.js generates five representative
variants (clean / blurry / dark / gridless / low-contrast) and the real
digitization pipeline runs over them. This test pins the deterministic
per-variant outcomes so the demo and the manual walkthrough behave
predictably. All inputs are synthetic; no diagnostic claim is made.
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
HARNESS = Path(__file__).resolve().parent / "js" / "samples_check.cjs"


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


def _variant(name):
    return _run()[name]


def test_clean_sample_passes_all_checks():
    out = _variant("clean")
    assert out["quality"]["checks_passed"] is True
    assert out["quality"]["warnings"] == []
    assert out["box"] is not None
    assert 7 <= out["scale"]["mm_per_px_x"] <= 9
    assert out["pointCount"] >= 30


def test_blurry_sample_flagged_and_still_extracts():
    out = _variant("blurry")
    assert out["quality"]["checks_passed"] is False
    assert "blurry" in out["quality"]["warnings"]
    assert out["box"] is not None
    assert out["pointCount"] >= 30


def test_dark_sample_flagged_too_dark_and_no_grid():
    out = _variant("dark")
    assert out["quality"]["checks_passed"] is False
    assert "too dark" in out["quality"]["warnings"]
    assert out["quality"]["brightness"] < 60
    assert out["box"] is None


def test_gridless_sample_has_no_grid():
    out = _variant("gridless")
    assert out["box"] is None
    assert out["pointCount"] == 0


def test_low_contrast_sample_flagged_low_contrast_and_no_grid():
    out = _variant("low-contrast")
    assert out["quality"]["checks_passed"] is False
    assert "low contrast" in out["quality"]["warnings"]
    assert out["quality"]["contrast_score"] < 15
    assert out["box"] is None


def test_all_variants_present_with_expected_dimensions():
    out = _run()
    assert set(out) == {"clean", "blurry", "dark", "gridless", "low-contrast"}
    for variant in out.values():
        assert variant["width"] == 800
        assert variant["height"] == 600
