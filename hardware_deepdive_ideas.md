# MEDHA LINK — Hardware Deep-Dive Ideas

> Four V1 hardware components, each with untapped potential for tier 2–3.
> V1 reference architecture: **Raspberry Pi 5** (see `docs/medha-link-hardware-v1.html`).
> The **ESP32 ₹5k prototype** described in `docs/architecture-freeze.md` §17 is a separate low-cost demo kit, not the V1 reference.
>
> Ideas only — nothing here is committed for implementation until selected.

---

## 1. Camera (CSI)

Three angles of value:

### Clinical vision
- Cyanosis (blue lips/fingertips), pupillary response, skin pallor for shock — the camera as a second set of eyes where SpO₂ sensors lie (poor perfusion).
- **Caution:** research-grade; lighting-sensitive; no clinical claim. Lowest priority of the three.

### Document scanning
- **Aadhaar ID scan** — Tesseract OCR runs locally on the Pi 5 (zero cloud) to autofill patient name/age in ~2 seconds.
- **Prescription scan** — OCR drug names into `patients.medical_history`.
- Most concrete, self-contained device feature; lives in the future `ambulance-app/`.

### Telemedicine
- Live **WebRTC** video stream ambulance → receiving doctor.
- **Wound photo** as a single JPEG (low bandwidth, high value) — the backend half of this (upload + handover attachment) is already being built as "Photo documentation" in Phase 1 of the software freeze.

---

## 2. UPS / Power connector

The power module is a **clinical signal**, not just a utility:

- **Runtime display** — "2h 14m remaining" + auto power-save on battery.
- **Vehicle vs. battery mode** — different sensor polling rates per power mode (maps to `vital.source` semantics in the data model).
- **Solar input** — the 9–30 V DC input already accepts a 12 V panel; rural CHCs can run off-grid.
- **Charge-cycle counter** — predictive battery replacement before field failure.

Device-side daemon/firmware work; no backend surface. Spec for the device app only.

---

## 3. Body temperature (DS18B20) → SIRS / Sepsis score

The biggest untapped one:

```
Flag SIRS if 2 of 4:
  Temp > 38°C or < 36°C    ← DS18B20
  HR > 90                   ← ECG/SpO₂ module
  RR > 20                   ← derivable
  Suspected infection       ← one checkbox
```

Missed sepsis is a top cause of preventable rural death — and this is just math, no ML.
Now implemented as the **SIRS screening** part of the clinical scoring service (`services/clinical.py`), with a persisted `risk_changed` event (see `docs/tier2-3-feature-specs.md`).

---

## 4. Hybrid Logical Clock (HLC)

The sync layer's HLC is already built (`backend/app/services/sync/hlc.py`, `hlc.js`). Three ideas beyond the current build:

### Full encounter replay
All events are causally ordered, so the entire ambulance run can be scrubbed as a timeline for training/debriefing. Now part of the software freeze as "Unified HLC timeline + replay."

### Multi-kit mass casualty
3 ambulances, 1 incident — HLC merges all 3 case streams in correct causal order on the hospital dashboard.
- **Status:** post-freeze (roadmap). Needs an `incident` entity + cross-case HLC merge.

### Medico-legal audit trail
HLC timestamps are tamper-evident (can't backdate without breaking the causal chain) — a court-admissible event sequence.
- Reinforced by the persisted `risk_changed` events (scoring snapshots with `scoring_version`).

---

## Recommendation

Software-first: the three ideas that belong to the frozen software scope are already scheduled (photo documentation, SIRS, full encounter replay). The rest (clinical vision, power telemetry, mass casualty, telemedicine) stay on the roadmap until the **₹5k ESP32 prototype / Pi 5 physical build** begins.
