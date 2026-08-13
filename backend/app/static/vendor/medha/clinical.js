"use strict";
/* NEWS2-5 + SIRS clinical scoring (freeze feature 2 + 3).
 *
 * Pure, DOM-free mirror of backend/app/services/clinical.py — the exact same
 * specification. The Node contract harness (tests/js/clinical_check.cjs)
 * asserts these two implementations produce identical results, so a case can
 * never show two different risk levels. When you change one, change both.
 *
 * Contract: docs/tier2-3-feature-specs.md §2-3 (news2-5-v1).
 */

(function (global) {
  const SCORING_VERSION = "news2-5-v1";

  // Canonical component order, used for tie-breaking and stable serialization.
  const COMPONENT_KEYS = [
    "rr",
    "spo2",
    "systolic_bp",
    "heart_rate",
    "temperature",
  ];

  // Component key -> attribute on a vital observation object.
  const ATTRS = {
    rr: "respiratory_rate",
    spo2: "spo2",
    systolic_bp: "systolic_bp",
    heart_rate: "heart_rate",
    temperature: "temperature",
  };

  // Contributor label per component key.
  const LABELS = {
    rr: "RR",
    spo2: "SpO₂",
    systolic_bp: "SBP",
    heart_rate: "Pulse",
    temperature: "Temp",
  };

  // NEWS2-5 scoring: [lower, upper, score] inclusive ranges, first match wins.
  const NEWS2_RANGES = {
    rr: [[25, 999, 3], [21, 24, 2], [12, 20, 0], [9, 11, 1], [0, 8, 3]],
    spo2: [[0, 91, 3], [92, 93, 2], [94, 95, 1], [96, 100, 0]],
    systolic_bp: [[0, 90, 3], [91, 100, 2], [101, 110, 1], [111, 219, 0], [220, 999, 3]],
    heart_rate: [[0, 40, 3], [41, 50, 1], [51, 90, 0], [91, 110, 1], [111, 130, 2], [131, 999, 3]],
    temperature: [[0, 35.0, 3], [35.1, 36.0, 1], [36.1, 38.0, 0], [38.1, 39.0, 1], [39.1, 999, 2]],
  };

  // Direction arrows: [low threshold, high threshold, low label, high label].
  const DIRECTIONS = {
    rr: [12, 20, "RR ↓", "RR ↑"],
    spo2: [96, 95, "SpO₂ ↓", "SpO₂ ↓"],
    systolic_bp: [111, 219, "SBP ↓", "SBP ↑"],
    heart_rate: [51, 90, "Pulse ↓", "Pulse ↑"],
    temperature: [36.1, 38.0, "Temp ↓", "Temp ↑"],
  };

  // SIRS criteria: key -> [low, high] window; met when strictly outside.
  const SIRS_WINDOW = {
    temperature: [36.0, 38.0], // temp >38 or <36
    heart_rate: [null, 90], // HR >90
    respiratory_rate: [null, 20], // RR >20
  };

  function componentValue(vital, key) {
    const value = vital == null ? undefined : vital[ATTRS[key]];
    return value === undefined || value === null ? null : Number(value);
  }

  function scoreValue(key, value) {
    if (value === null) return 0;
    for (const [lower, upper, score] of NEWS2_RANGES[key]) {
      if (lower <= value && value <= upper) return score;
    }
    return 0;
  }

  function riskClass(score, components) {
    if (score >= 7) return "high";
    if (score >= 5 || Math.max(...Object.values(components)) === 3) return "medium";
    return "low";
  }

  function contributorDirection(key, value) {
    const [low, high, lowLabel, highLabel] = DIRECTIONS[key];
    if (value !== null && value > high) return highLabel;
    return lowLabel;
  }

  function computeNews2(vital) {
    const components = {};
    for (const key of COMPONENT_KEYS) {
      components[key] = scoreValue(key, componentValue(vital, key));
    }
    const total = Object.values(components).reduce((a, b) => a + b, 0);

    const keyOrder = {};
    COMPONENT_KEYS.forEach((key, index) => {
      keyOrder[key] = index;
    });
    const scored = [];
    for (const key of COMPONENT_KEYS) {
      if (components[key] >= 2) scored.push([key, components[key]]);
    }
    scored.sort((a, b) => b[1] - a[1] || keyOrder[a[0]] - keyOrder[b[0]]);
    const contributors = scored.map(([key]) => contributorDirection(key, componentValue(vital, key)));

    return {
      score: total,
      risk_class: riskClass(total, components),
      components,
      contributors,
    };
  }

  function outsideWindow(value, low, high) {
    if (value === null) return false;
    if (low !== null && value < low) return true;
    if (high !== null && value > high) return true;
    return false;
  }

  function computeSirs(vital, suspected_infection) {
    const criteria = {
      temperature: outsideWindow(componentValue(vital, "temperature"), ...SIRS_WINDOW.temperature),
      heart_rate: outsideWindow(componentValue(vital, "heart_rate"), ...SIRS_WINDOW.heart_rate),
      respiratory_rate: outsideWindow(
        componentValue(vital, "rr"),
        ...SIRS_WINDOW.respiratory_rate
      ),
      suspected_infection: Boolean(suspected_infection),
    };
    const metCount = Object.values(criteria).filter(Boolean).length;
    return {
      met: metCount >= 2,
      criteria_met: metCount,
      criteria,
    };
  }

  const api = { computeNews2, computeSirs, SCORING_VERSION, COMPONENT_KEYS };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.MedhaClinical = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
