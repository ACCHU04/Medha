# MEDHA LINK — Architecture Freeze

> Canonical structure document. Date: 2026-08-13.
> Implementation specs live in `docs/tier2-3-feature-specs.md`.
>
> **Key principle:** simple interface on top, sophisticated system underneath. A paramedic understands the app in seconds; a judge/doctor can drill into the technical details.

---

## 1. Overall system

```text
                         MEDHA LINK
                              │
          ┌───────────────────┴───────────────────┐
          │                                       │
      AMBULANCE                               HOSPITAL
       DEVICE                                 DASHBOARD
          │                                       │
          ▼                                       ▼
   Patient / Vitals                         Incoming Cases
   ECG / GPS / Camera                       Vitals / Risk
          │                                  ETA / GPS
          │                                  Accept / Prepare
          ▼                                       │
     EDGE SOFTWARE                                 │
          │                                       │
    Offline Outbox                                 │
          │                                       │
          └───────────────┬───────────────────────┘
                          ▼
                    MEDHA BACKEND
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
           REST API    WebSocket     Sync
              │           │           │
              └───────────┼───────────┘
                          ▼
                     PostgreSQL
```

## 2. Ambulance application — four main tabs

```text
┌─────────────────────────────────────┐
│ MEDHA LINK       AMB-07   🟢 ONLINE │
├─────────────────────────────────────┤
│          CURRENT TAB                │
├─────────────────────────────────────┤
│ Patient │ Vitals │ ECG │ Hospital  │
└─────────────────────────────────────┘
```

### Tab 1 — Patient (the simplest screen)

```text
PATIENT
Rahul Kumar
45 years • Male

Case
ML-00021

Chief complaint
Chest discomfort

Severity
● Moderate

ENCOUNTER
✓ Case created
✓ Scene arrival
● Transporting
○ Hospital arrival
○ Closed

[Timeline ▼]
```

Patient info + case status + timeline is enough. Don't show everything here.

### Tab 2 — Vitals (most important operational screen)

```text
LIVE VITALS
┌──────────┐ ┌──────────┐
│ HR       │ │ SpO₂     │
│ 82 BPM   │ │ 97 %     │
└──────────┘ └──────────┘
┌──────────┐ ┌──────────┐
│ BP       │ │ RR       │
│ 120/80   │ │ 18/min   │
└──────────┘ └──────────┘
Temperature
37.1 °C

RISK ASSESSMENT
NEWS2-5
Score 2
LOW RISK

SIRS
No criteria threshold reached

GPS ✓       SYNC ✓
```

Tap **Risk Assessment** for the advanced sheet:

```text
NEWS2-5
Respiratory rate       +0
SpO₂                    +0
Heart rate              +0
Blood pressure          +0
Temperature             +0
TOTAL: 2

Decision-support only.
Clinician review required.
```

### Tab 3 — ECG

```text
PAPER ECG
ECG PREVIEW  [~~~~~ waveform ~~~~~]
Quality ✓ Good · Grid detected ✓ · Trace extracted ✓
[ CAPTURE ECG ]

DECISION SUPPORT
ECG signal reviewed — no obvious ST-elevation pattern detected.
Clinician review required.
Decision-support prototype — not a diagnosis.
```

**Forbidden UI wording:** "STEMI detected", "Patient has myocardial infarction". No diagnosis language.

### Tab 4 — Hospital (transport coordination)

```text
DESTINATION
MEDHA City Hospital
ETA 8 min  (prototype calc)
🚑 ──────────── 🏥

ACCEPTANCE ✓ ACCEPTED
PREPARATION ✓ READY FOR ARRIVAL

Hospital capabilities
✓ Trauma ✓ Emergency ✓ CT ✓ ICU

[ VIEW HOSPITAL ]
```

If declined:

```text
CANNOT ACCEPT
Reason: ICU unavailable
Recommended destination: Ruby Hall Hospital — ETA 11 min
[ SELECT RECOMMENDED ]
```

### 6. Demo controls — never in the main UI

```text
⚙ DEMO CONTROLS
Scenario [ Normal ▼ ] · Telemetry [ START ] · Deterioration [ SIMULATE ]
Connectivity [ OFFLINE ] [ RESTORE ]
Lifecycle [ Scene Arrival ] [ Transport ] [ Hospital Arrival ] [ Close ]
[ RESET DEMO ]
```

## 7. Hospital dashboard — command center

```text
MEDHA LINK — HOSPITAL COMMAND CENTER
MEDHA CITY HOSPITAL             🟢 ONLINE

INCOMING EMERGENCIES
🚨 ML-00021  CRITICAL  ETA 6 MIN   Chest pain  AMB-07  ACCEPTED
⚠  ML-00022  MODERATE  ETA 14 MIN  Trauma      AMB-04  PENDING

SELECTED CASE
```

### 8. Hospital case detail

1. **Patient** — Rahul Kumar · 45M · Chest discomfort · AMB-07
2. **Live vitals** — HR 118 · SpO₂ 91% · BP 105/68 · RR 26 · Temp 38.1°C (critical values red)
3. **Risk** — NEWS2-5 HIGH · SIRS 2 criteria · ⚠ CLINICIAN REVIEW
4. **Transport** — ETA 6 min · Distance 3.2 km · GPS LIVE · [MAP] (route bar: 🚑 traveled → 🏥 destination)
5. **Pre-arrival** — Required: Emergency team ✓ Bed ✓ CT ✓ → [ ACCEPT ] [ CANNOT ACCEPT ] → after accept [ PREPARE ] → 🟢 READY FOR ARRIVAL

### 9. Hospital ECG
Captured time, quality ✓, waveform, "Decision-support signal — clinician review required. Not a diagnosis."

### 10. Encounter timeline (one timeline on both sides)

```text
14:21 ✓ CASE CREATED        14:31 ✓ HOSPITAL ACCEPTED
14:22 ✓ SCENE ARRIVAL       14:32 ✓ PREPARATION STARTED
14:24 ✓ TRANSPORT STARTED   14:35 ✓ READY FOR ARRIVAL
14:27 ✓ VITALS RECEIVED     14:39 ○ HOSPITAL ARRIVAL
14:29 ⚠ CONDITION CHANGED
14:30 ✓ ECG CAPTURED
```

The unified, HLC-ordered timeline is the source of truth; replay moves through it.

### 11. Geofence (automatic — no extra button)

```text
GPS 8.2 km → 5.0 km → GEOFENCE ENTERED → 🏥 HOSPITAL ALERT
"AMBULANCE APPROACHING" → PREPARE
```

### 12. Specialty hospital recommendation (no complicated screen)

```text
RECOMMENDED DESTINATION — Chest pain
MEDHA City Hospital
✓ Cardiology ✓ ICU ✓ Emergency
ETA 8 min [ SELECT ]
```

If no specialty match: "No specialty match found. Nearest suitable hospital: Ruby Hall — ETA 11 min."

### 13. Handover

```text
DIGITAL HANDOVER
✓ Patient ✓ Encounter timeline ✓ Vitals ✓ ECG ✓ GPS ✓ Hospital acceptance ✓ Preparation
Completeness 100%
[ FHIR JSON ] [ CDA XML ] [ PRINT / PDF ]

"Export of prehospital monitoring data; research prototype, not a certified medical record."
```

## 14. Frontend architecture (decision: stay vanilla JS + FastAPI for this prototype)

> The frontend should not directly contain all the logic. Decision-support is backend-authoritative.
> React/Next.js + Zustand is the documented **future** target, not a current build item.

```text
Phase-1 UI (vanilla JS) served by FastAPI static mount
├── Ambulance UI (Patient · Vitals · ECG · Hospital) + Demo Controls
├── Hospital UI (Queue · Case · Vitals · Transport · ECG · Handover)
├── Shared: encounter timeline, clinical.js scoring, demo banner
└── State: module-scoped JS state per screen (no framework)
        ▼
     Sync engine (outbox + HLC)
        ▼
       FastAPI (cases, vitals, ECG, GPS, hospital, handover, sync)
        ▼
     PostgreSQL
```

## 15. AI / decision-support layer (behind the normal UI)

```text
Vitals
  ├── NEWS2-5
  ├── SIRS
  └── trend analysis
          ▼
  Decision-support engine (backend) + clinical.js (instant UI) — contract-locked
          ▼
  Human-readable signal
          ▼
  Clinician review
```

Never `AI → Diagnosis → Automatic treatment`. Always `AI → Signal / risk indication → Human review`.

## 16. Offline architecture (major differentiator)

```text
SENSOR / USER ACTION → LOCAL STORE → OUTBOX → NETWORK?
                                          ↙          ↘
                                        NO            YES
                                        ↓             ↓
                                      QUEUE        /sync/push
                                        ↓             ↓
                                        └──────┬──────┘
                                               ↓
                                            DEDUPE → HLC → PostgreSQL → WebSocket → Hospital
```

UI shows only `🟢 ONLINE / ✓ SYNCED` or `🟠 OFFLINE / N RECORDS QUEUED`. No HLC terminology exposed.

## 17. Hardware V1

- **Reference V1:** Raspberry Pi 5 — see `docs/medha-link-hardware-v1.html`.
- **₹5k prototype (separate low-cost demo kit):** ESP32 · MAX30102 · AD8232 · NEO-6M · temperature sensor · OLED · SD card · ESP32-CAM · battery/power bank · enclosure.
- Sensor measurements are **prototype/demo measurements**, not clinically validated readings — clearly labeled as such.

## 18. Future hardware

- **V1.5:** ESP32 → 4G modem → GPS → ECG → SpO₂ → BP → temperature → battery/UPS.
- **V2:** multi-lead ECG, better ECG AFE, medically appropriate sensors, ambulance power integration, oxygen equipment telemetry, rugged enclosure, larger touchscreen, secure device management.
- **Much later:** clinical validation, regulatory pathway, validated algorithms, advanced ECG decision support, real routing/operational ETA integration, hospital system integration.

---

# Post-freeze improvements (accepted into scope)

## I. Case State summary (both screens, single compact status)
- AMBULANCE: `TRANSPORTING · ETA 8 MIN · HOSPITAL ACCEPTED`
- HOSPITAL: `INBOUND · 8 MIN · PREPARING`

## II. "Why this hospital?" explanation
`Recommended because: Cardiology capability + 8.2 km · Alternative: Ruby Hall — 10.7 km`

## III. Data freshness indicator
- Online: `LIVE · GPS 4s ago · Vitals 3s ago`
- Offline: `OFFLINE · 7 records queued · Last sync 42s ago`

## IV. Explainable risk
`NEWS2-5: 7 · HIGH · Main contributors: RR ↑ · SpO₂ ↓ · Pulse ↑ · Clinician review required`

## V. Pre-arrival readiness score
```text
PRE-ARRIVAL READINESS
Patient information ✓   Vitals received ✓   ECG received ✓
Hospital accepted ✓     Bed prepared ✓      Team prepared ✓
6 / 6 READY  →  🟢 READY FOR ARRIVAL
```

## VI. Timeline as central source of truth
Unified HLC timeline with risk transitions (`risk_changed` events) — replay scrubs this one timeline.

## VII. Demo Mode banner
Persistent `DEMO / RESEARCH PROTOTYPE` banner on both screens (simulated data made explicit).

## Mission Overview (hospital dashboard top)
```text
ACTIVE TRANSFER
Rahul Kumar · 45M            AMB-07
Chest discomfort
🚑 3.2 km ──────────────→ 🏥 MEDHA CITY     ETA 6 MIN
ACCEPTED  PREPARING  🟢 READY FOR ARRIVAL
VITALS ✓  ECG ✓  GPS ✓  HANDOVER 6/6
```

---

# Final scope (the STOP list)

**Build:** specialty routing · NEWS2-5 + SIRS · persisted `risk_changed` · geofence→prepare · photo documentation · unified HLC timeline + replay · UI restructure (4-tab ambulance, command center, Mission Overview, Case State, freshness, explainable risk, readiness, demo banner) · scripted end-to-end demo.

**NOT adding:** more tabs · more AI panels · chatbot everywhere · complex analytics dashboards · dozens of settings · real clinical diagnosis · multi-lead AI before real hardware · mass-casualty mode · telemedicine/WebRTC · React migration · SMS/STEMI beyond spec.

---

# Final product story

> **MEDHA LINK is an offline-first ambulance edge system that captures prehospital information, maintains it during connectivity loss, provides transport/risk awareness, alerts and prepares the receiving hospital before arrival, and produces a structured digital handover.**

Demo flow: 🚑 Ambulance → Patient → Vitals → Risk assessment → ECG → GPS + ETA → Hospital recommendation → 📴 Internet lost (data continues locally) → 📶 Network restored → 🏥 ACCEPT → PREPARE → 📍 Geofence → READY BEFORE ARRIVAL → HOSPITAL ARRIVAL → FHIR / CDA HANDOVER.
