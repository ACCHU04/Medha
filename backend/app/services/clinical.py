"""Clinical scoring: NEWS2-5 + SIRS (freeze feature 2 + 3).

Pure functions over a vital observation — no DB access. The exact same
specification is mirrored in ``app/static/vendor/medha/clinical.js`` and
locked by the Node contract tests in ``tests/test_js_clinical.py``. A case
must never show two different risk levels, so this module is the source of
truth for the backend and ``clinical.js`` must stay equivalent.

Scoring tables and the documented deviations are defined in
``docs/tier2-3-feature-specs.md`` §2-3:
- NEWS2-5 = standard NEWS2 with the 5 measured params (O2 / AVPU rows omitted
  until the ``oxygen_administered`` / ``consciousness`` fields exist). Version
  tag ``news2-5-v1``.
- SIRS = 2 of 4 criteria (temp, HR, RR, ``suspected_infection`` flag).
"""

from dataclasses import dataclass, field
from typing import Any

from ..models import Vital

SCORING_VERSION = "news2-5-v1"

# Canonical component order, used for tie-breaking and stable serialization.
COMPONENT_KEYS = ("rr", "spo2", "systolic_bp", "heart_rate", "temperature")

# Component key -> attribute on the Vital model (``rr`` is respiratory_rate).
_ATTRS: dict[str, str] = {
    "rr": "respiratory_rate",
    "spo2": "spo2",
    "systolic_bp": "systolic_bp",
    "heart_rate": "heart_rate",
    "temperature": "temperature",
}

# Contributor label per component key.
_LABELS = {
    "rr": "RR",
    "spo2": "SpO₂",
    "systolic_bp": "SBP",
    "heart_rate": "Pulse",
    "temperature": "Temp",
}

# NEWS2-5 scoring: (lower, upper, score) inclusive ranges, first match wins.
# Matches the spec table: RR / SpO2 / SBP / Pulse / Temp with O2 + AVPU rows
# omitted (documented news2-5-v1 deviation).
_NEWS2_RANGES: dict[str, list[tuple[float, float, int]]] = {
    "rr": [(25, 999, 3), (21, 24, 2), (12, 20, 0), (9, 11, 1), (0, 8, 3)],
    "spo2": [(0, 91, 3), (92, 93, 2), (94, 95, 1), (96, 100, 0)],
    "systolic_bp": [
        (0, 90, 3),
        (91, 100, 2),
        (101, 110, 1),
        (111, 219, 0),
        (220, 999, 3),
    ],
    "heart_rate": [
        (0, 40, 3),
        (41, 50, 1),
        (51, 90, 0),
        (91, 110, 1),
        (111, 130, 2),
        (131, 999, 3),
    ],
    "temperature": [
        (0, 35.0, 3),
        (35.1, 36.0, 1),
        (36.1, 38.0, 0),
        (38.1, 39.0, 1),
        (39.1, 999, 2),
    ],
}

# Direction arrows: (low threshold, high threshold, low label, high label).
# A component outside its NEWS2 zero band contributes with a direction.
_DIRECTIONS: dict[str, tuple[float, float, str, str]] = {
    "rr": (12, 20, "RR ↓", "RR ↑"),
    "spo2": (96, 95, "SpO₂ ↓", "SpO₂ ↓"),
    "systolic_bp": (111, 219, "SBP ↓", "SBP ↑"),
    "heart_rate": (51, 90, "Pulse ↓", "Pulse ↑"),
    "temperature": (36.1, 38.0, "Temp ↓", "Temp ↑"),
}

# SIRS criteria: key -> (low, high) window; met when strictly outside.
_SIRS_WINDOW: dict[str, tuple[float | None, float | None]] = {
    "temperature": (36.0, 38.0),  # temp >38 or <36
    "heart_rate": (None, 90),  # HR >90
    "respiratory_rate": (None, 20),  # RR >20
}


@dataclass
class News2Outcome:
    score: int = 0
    risk_class: str = "low"
    components: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in COMPONENT_KEYS}
    )
    contributors: list[str] = field(default_factory=list)


@dataclass
class SirsOutcome:
    met: bool = False
    criteria_met: int = 0
    criteria: dict[str, bool] = field(default_factory=dict)


def _component_value(vital: Vital, key: str) -> float | None:
    value = getattr(vital, _ATTRS[key], None)
    if value is None:
        return None
    return float(value)


def _score_value(key: str, value: float | None) -> int:
    if value is None:
        return 0
    for lower, upper, score in _NEWS2_RANGES[key]:
        if lower <= value <= upper:
            return score
    return 0


def _risk_class(score: int, components: dict[str, int]) -> str:
    # Any single parameter = 3 forces at least medium (spec §2).
    if score >= 7:
        return "high"
    if score >= 5 or max(components.values()) == 3:
        return "medium"
    return "low"


def _contributor_direction(key: str, value: float | None) -> str:
    low, high, low_label, high_label = _DIRECTIONS[key]
    if value is not None and value > high:
        return high_label
    return low_label


def compute_news2(vital: Vital) -> News2Outcome:
    """NEWS2-5 score for a vital observation. Missing params score 0."""
    components = {
        key: _score_value(key, _component_value(vital, key)) for key in COMPONENT_KEYS
    }
    total = sum(components.values())

    key_order = {key: index for index, key in enumerate(COMPONENT_KEYS)}
    contributors = [
        (key, components[key])
        for key in COMPONENT_KEYS
        if components[key] >= 2
    ]
    contributors.sort(key=lambda pair: (-pair[1], key_order[pair[0]]))
    contributor_labels = [
        _contributor_direction(key, _component_value(vital, key))
        for key, _score in contributors
    ]

    return News2Outcome(
        score=total,
        risk_class=_risk_class(total, components),
        components=components,
        contributors=contributor_labels,
    )


def _outside_window(value: float | None, low: float | None, high: float | None) -> bool:
    if value is None:
        return False
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    return False


def compute_sirs(vital: Vital, suspected_infection: bool | None = None) -> SirsOutcome:
    """SIRS screening: 2 of 4 criteria. Missing params count as not met."""
    criteria = {
        "temperature": _outside_window(
            _component_value(vital, "temperature"), *_SIRS_WINDOW["temperature"]
        ),
        "heart_rate": _outside_window(
            _component_value(vital, "heart_rate"), *_SIRS_WINDOW["heart_rate"]
        ),
        "respiratory_rate": _outside_window(
            _component_value(vital, "rr"), *_SIRS_WINDOW["respiratory_rate"]
        ),
        "suspected_infection": bool(suspected_infection),
    }
    met_count = sum(1 for value in criteria.values() if value)
    return SirsOutcome(
        met=met_count >= 2,
        criteria_met=met_count,
        criteria=criteria,
    )


def news2_payload(vital: Vital) -> dict[str, Any]:
    """The shared NEWS2-5 output shape from the freeze spec §2."""
    outcome = compute_news2(vital)
    return {
        "score": outcome.score,
        "risk_class": outcome.risk_class,
        "components": outcome.components,
        "contributors": outcome.contributors,
    }


def sirs_payload(vital: Vital, suspected_infection: bool | None = None) -> dict[str, Any]:
    """The shared SIRS output shape from the freeze spec §3."""
    outcome = compute_sirs(vital, suspected_infection)
    return {
        "met": outcome.met,
        "criteria_met": outcome.criteria_met,
        "criteria": outcome.criteria,
    }
