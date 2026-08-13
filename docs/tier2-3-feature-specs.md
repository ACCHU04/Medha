# MEDHA LINK — Tier 2–3 Feature Specs

> Authoritative implementation spec for the frozen Phase 1 feature set.
> Source of truth for the build. Every feature must pass its contract tests before the next feature starts.
> Date: 2026-08-13. Stack: FastAPI + PostgreSQL + vanilla JS (Phase-1 UI) + Node contract harness.

---

## 0. Contracts (non-negotiable)

1. **NEWS2/SIRS parity** — one shared specification implemented in `clinical.js` (instant UI) and `clinical.py` (handover/SMS/geofence authority). Locked by Node contract tests. A case must never show two different risk levels.
2. **Offline behavior** — local queue → continue capture → sync → dedupe → HLC. UI shows only `🟢 ONLINE / ✓ SYNCED` or `🟠 OFFLINE / N RECORDS QUEUED`. No HLC terminology exposed.
3. **Timeline** — vitals + events + GPS merged by HLC order into a single encounter replay.
4. **Hospital workflow** — transport → destination → accept → prepare → geofence → READY FOR ARRIVAL → hospital arrival.
5. **Safety language** — risk/screening/decision-support wording only ("NEWS2-5: High risk — clinician review required"). Never diagnosis or automatic treatment. ECG boundary statement stays visible.

---

## 1. Specialty-aware routing

**Goal:** recommend the *right* hospital, not just the nearest.

### Design
- New `backend/app/services/routing.py`:
  - `COMPLAINT_CAPABILITIES`: keyword map — `chest pain|cardiac → cardiology`, `trauma|RTA|fall|crash → trauma`, `labour|pregnancy|maternity → maternity`, `child|pediatric → pediatric`, default `general`.
  - `recommend_hospital(db, case, exclude_id=None) -> Recommendation | None` where `Recommendation = {hospital, matched_capabilities: list[str], distance_km: float, alternatives: list[{hospital, distance_km}]}`.
  - Candidate scoring: hospitals whose `capabilities` (JSONB boolean tags, per seed) contain ≥1 required tag, sorted by `haversine_km`. If no hospital matches, fall back to distance-only (never no-answer).
- **Call-site upgrades** (both currently call `nearest_hospital`):
  - `services/case_lifecycle.py` — `transport_start` fallback destination.
  - `services/case.py::decline_case` — the recommended hospital after a decline.
- **Schema:** `CaseOut` gains `recommendation: RecommendationOut | None` (surfaces the "Why this hospital?" reason — matched capabilities + distance + alternatives).

### UI ("Why this hospital?")
```
Recommended because: Cardiology capability + 8.2 km
Alternative: Ruby Hall — 10.7 km
```

### Tests
Tag mapping · filter-then-distance ordering · no-match fallback · declined-hospital exclusion (`exclude_id`).

---

## 2. NEWS2-5

### Scoring tables (standard NEWS2, 5 measured params)

| Param | 3 | 2 | 1 | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RR | ≤8 | — | 9–11 | 12–20 | — | 21–24 | ≥25 |
| SpO₂ | ≤91 | 92–93 | 94–95 | ≥96 | — | — | — |
| SBP | ≤90 | 91–100 | 101–110 | 111–219 | — | — | ≥220 |
| Pulse | ≤40 | — | 41–50 | 51–90 | 91–110 | 111–130 | ≥131 |
| Temp | ≤35.0 | — | 35.1–36.0 | 36.1–38.0 | 38.1–39.0 | ≥39.1 | — |

- Risk: **0–4 low** · **5–6 medium** · **≥7 high**. Any single parameter = 3 forces at least medium.
- **"NEWS2-5" deviation (documented):** O₂ administration + AVPU rows omitted until `oxygen_administered` / `consciousness` fields are added. Version tag `news2-5-v1`.

### Output (shared shape)
```json
{
  "score": 7,
  "risk_class": "high",
  "components": { "rr": 3, "spo2": 2, "systolic_bp": 0, "heart_rate": 2, "temperature": 0 },
  "contributors": ["SpO₂ ↓", "RR ↑"]
}
```

### Implementation
- `backend/app/services/clinical.py` + `backend/app/static/vendor/medha/clinical.js` (identical spec).
- Parity via `tests/js/clinical_check.cjs` + `tests/test_js_clinical.py` + Python matrix test.
- Contract coverage: totals, per-component scores, contributor strings (with direction ↓/↑), risk class mapping, edge cases (missing params → that component 0).

---

## 3. SIRS screening

### Criteria (2 of 4)
Temp >38 or <36 · HR >90 · RR >20 · `suspected_infection` flag (new nullable bool on the vitals POST payload — payload-only, no table change).

### Output
```json
{ "met": false, "criteria_met": 1, "criteria": { "temperature": true, "heart_rate": false, "respiratory_rate": false, "suspected_infection": true } }
```

---

## 4. Persisted `risk_changed` event

### Trigger rule
Persisted **only on meaningful transition**, never per-vital:
- NEWS2-5 **total score changes** (even within the same risk class), or
- SIRS **state flips** (met ↔ not met).

Baseline rule: the first computed state after monitoring starts creates the initial event, so every timeline starts from a known baseline.

### Event shape (`CaseEventType.risk_changed`)
```json
{
  "event_type": "risk_changed",
  "payload": {
    "scoring_version": "news2-5-v1",
    "news2_5": {
      "previous": { "score": 3, "risk_class": "moderate" },
      "current":  { "score": 7, "risk_class": "high" },
      "contributors": ["SpO₂ ↓", "RR ↑"]
    },
    "sirs": {
      "previous": { "met": false, "criteria_met": 0 },
      "current":  { "met": true,  "criteria_met": 2 }
    }
  },
  "hlc": "<...>",
  "device_id": "<source>",
  "created_at": "<utc>"
}
```

### Evaluation points
Both vital-ingress paths evaluate and persist:
- `POST /api/v1/cases/{case_id}/vitals` (`routes/vitals.py`)
- sync batch push (`services/sync/apply.py`)

Both already broadcast; the new event fans out via `broadcast_case_event`.

### Files
- `models/enums.py` — add `CaseEventType.risk_changed`
- `services/clinical.py` — scoring
- `services/risk.py` — `evaluate_and_persist_risk(db, case, vital)` (compare → persist only on change)
- `routes/vitals.py` + `services/sync/apply.py` — hooks

### Consumers
WS broadcast · unified timeline · encounter replay · handover (risk history section).

### Tests
Baseline creation · score change within class · SIRS flip · no-op (unchanged) persists nothing · REST and sync paths · payload shape incl. `scoring_version`.

---

## 5. Geofence → hospital preparation

### Design
- `backend/app/services/geofence.py`: `RADIUS_KM = 5.0` (config); `maybe_auto_prepare(db, case, point)`:
  1. skip unless `status == transporting` and `acceptance == accepted` and `prepared_at is None`
  2. destination = `case.hospital`; require lat/lon; `haversine_km(hospital, fix) <= RADIUS_KM`
  3. call existing prepare path with `auto=True`, `bed_type=None`, `notes="Auto-prepared by geofence"`
  4. silent skip on 409 (idempotent via `prepared_at` guard)
- `prepare_case(..., auto=True)` keyword in `services/case.py`; event payload gains `"auto": True`.
- Hook in `POST /cases/{case_id}/gps` after `broadcast_gps`.
- UI: existing `READY FOR ARRIVAL` badge + "Auto-prepared (geofence)" label.

### Tests
Fix inside/outside radius · not-accepted · already-prepared · closed case.

---

## 6. Photo documentation

### Schema (migration)
New table `case_photos`: `id` (uuid pk), `case_id` FK, `captured_by_id` FK users, `image` bytea, `caption` text nullable, `hlc`, `created_at`.

### Routes
- `POST /api/v1/cases/{case_id}/photos` (multipart) — capture/attach
- `GET  /api/v1/cases/{case_id}/photos` — list metadata
- `GET  /api/v1/cases/{case_id}/photos/{photo_id}/image` — image bytes

### Handover
Include JPEGs as FHIR R4 `DocumentReference` (attachment) + a CDA section. Fixes the verified "no image support today" gap.

### Tests
Upload → list → fetch · handover includes attachments · access rules mirror ECG/vitals read path (owning paramedic or hospital staff).

---

## 7. Unified HLC timeline + replay

### Endpoint
`GET /api/v1/cases/{case_id}/timeline` — merge, by HLC order:
- vitals (each with computed NEWS2-5 + SIRS snapshot), as `{t, kind: "vital", ...}`
- `case_events` (incl. `risk_changed`) as `{t, kind: "event", ...}`
- GPS fixes as `{t, kind: "gps", ...}`

### Replay
Dashboard replay (`app.js:915` `startReplay`/`replay-slider`) scrubs the unified timeline: vitals cards + event log + map position advance together.

### Tests
HLC ordering across mixed kinds · empty case · timeline includes risk transitions.

---

## 8. SMS fallback (EC25) — device-side spec (future)

- `modem_sms.py` (future `ambulance-app/`): pyserial on EC25 AT port; `AT+CMGF=1` → `AT+CMGS` → `>` prompt → payload + Ctrl-Z.
- Guarded by online/offline probe + min-interval/max-count throttle.
- Payload ≤160 chars: `MH-01 #AB12 CHEST PAIN, HR 118 SpO2 91 BP 140/90, ETA 18m, hosp: MEDHA. GPS <link>`.
- Queue drafts in the SQLite outbox; touchscreen shows queue counter.
- `hospitals.sms_number` (nullable) pushed to devices via sync/changes.
- **Status:** spec only — no code in this repo today.

---

## 9. STEMI flag on ECG — constrained, research-only (future)

- **Constraint (verified):** the digitizer extracts a single lead ("I") — `static/ambulance-simulator/app.js:1235`. Rule-based ST-elevation is not clinically meaningful on one lead.
- **Phase A (enabler):** multi-lead capture (operator crops each lead box; waveform `channels[]`).
- **Phase B (heuristic, research-only):** ST deviation 60–80 ms after J point; ≥1 mm in ≥2 contiguous limb leads (or ≥2 mm V2–V3 men / 1.5 mm women); stored in `ecg_tracings.quality.stemi_heuristic`; with `insufficient_leads` suppression. UI wording: "POSSIBLE STEMI — research heuristic, verify with cardiologist."
- **Status:** after multi-lead digitizer; not in this freeze.
