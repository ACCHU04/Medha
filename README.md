![MEDHA LINK](docs/medha-link-logo.png)

Real-time emergency response and pre-hospital care coordination — from the ambulance to the hospital bed, live.

---

## Overview

MEDHA LINK is a **pre-hospital (EMS) response coordination platform**. During an emergency the people who matter most are spread across moving vehicles and busy hospital floors, and the paper-based transfer of information is slow, lossy, and untraceable. MEDHA LINK keeps everyone on the same page in real time: the paramedic in the ambulance, the hospital staff waiting at the other end, and the doctors coordinating the response.

This repository is the **Phase 1 monorepo build-out**: a full-stack FastAPI + PostgreSQL system with realtime streaming, an offline-first sync layer, a paper-ECG digitization pipeline, FHIR/NABH-ready handover export, and a bilingual voice + text **AI assistant** embedded in the Phase-1 browser UIs.

> **Heads up — synthetic data only.** Everything here is generated locally for development and testing. Never use it with real patient information.

---

## What problem it solves

| Without MEDHA LINK | With MEDHA LINK |
| --- | --- |
| Paramedic fills forms on paper while the case is live | Patient + case data captured once, streamed to the hospital instantly |
| Hospital finds out "a case is coming" by phone | Dashboard shows the live case, vitals, and ETA the moment monitoring starts |
| Deterioration noticed only at handover | Vitals stream in real time; deterioration surfaces when it happens |
| Handover is verbal / hand-written | Structured digital handover with FHIR R4 + CDA export and vitals replay |
| Crew in a dead zone loses all data | Offline-first sync queues reconcile automatically on reconnect |

---

## Key features

- **Live vitals** — heart rate, SpO₂, blood pressure, temperature, and respiration stream from the ambulance to the hospital over WebSocket; deterioration surfaces the moment it happens.
- **Encounter lifecycle** — every case follows a forward-only state machine: `active → transporting → at_hospital → closed`, driven by typed events (`scene_arrival`, `transport_start`, `hospital_arrival`, `case_closed`, `severity_changed`). Illegal transitions are rejected with `409`.
- **Hospital transport coordination** — hospital staff **accept**, **decline**, or **prepare** a case before the ambulance arrives; a declined destination falls back to the nearest hospital automatically.
- **GPS tracking & ETA** — fixes stream to `/ws/cases/{id}/vitals` and are drawn on a Leaflet map. ETA prefers the OSRM routed polyline (scaled by how far along it the ambulance is) and falls back to straight-line haversine at a constant speed.
- **Paper ECG digitization** — capture the tracing offline, extract + normalize it in the browser, sync it to the backend, and view it on the hospital dashboard with a manual quality checklist (`docs/ecg-quality-walkthrough.md`).
- **Digital handover** — a structured record with vitals replay, exportable as a **FHIR R4 JSON Bundle** (`application/fhir+json`), **CDA R2-style XML**, and a printable human-readable view (`docs/handover-walkthrough.md`).
- **Offline-first sync** — pull/push queues let clients work disconnected and reconcile when they reconnect; every row carries an HLC (hybrid logical clock) for conflict-aware ordering.
- **Auth & roles** — JWT bearer auth with `paramedic`, `doctor`, and `hospital_admin` roles; bcrypt-hashed passwords; resource-level ownership rules.
- **Realtime everywhere** — a connection manager broadcasts vitals, case events, and GPS fixes to every subscribed client (REST and sync both publish into the same stream).
- **MEDHA AI assistant** — bilingual (en-IN / hi-IN) voice + text assistant that fills patient and case forms, triggers actions, answers live-state questions, and reads replies aloud.

---

## How a response flows

```text
 1. Paramedic logs in                   2. Patient + case created
    (JWT, role=paramedic)                  (POST /api/v1/patients, /cases)

 3. Monitoring starts  ──────────────►  vitals stream over
    (ambulance simulator)                 /ws/cases/{id}/vitals

 4. Hospital dashboard                 5. Doctor / admin accepts,
    sees the case live                    declines, or prepares
    (vitals, severity, ETA)               (POST /cases/{id}/accept|decline|prepare)

 6. Transport starts ──► route polyline  7. GPS fixes + ETA update
    + destination hospital assigned        live on both screens

 8. Hospital arrival ──► case becomes   9. Case closed ──► structured digital
    at_hospital                           handover (FHIR / CDA / printable)
```

---

## Architecture

```text
                 MEDHA LINK
                     |
       +-------------+-------------+
       |             |             |
       v             v             v
 Ambulance      Hospital      Doctor
 Simulator      Dashboard     Console
 (Phase-1 UI)   (Phase-1 UI)   (future)
       |             |             |
       +-------------+-------------+
                     v
                Backend (FastAPI)
                app/models, routes,
                schemas, services
                     |
       +-------------+-------------+
       |             |             |
       v             v             v
  PostgreSQL     Realtime      Sync layer
  (Alembic      (WebSocket   (offline-first
   migrations)   streams)     push/pull)
```

**Realtime data flow**

```text
Ambulance simulator ──vitals/events──►  WebSocket (/ws/cases/{id}/vitals)
                                            │
                                            ▼
Hospital dashboard ──live updates──►  Paramedic / Doctor / Admin
```

The same broadcast layer is shared by REST writes, the sync push path, and the WebSocket streams — so however data enters the system, every connected client sees it instantly.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2 |
| Database | PostgreSQL 16 (Docker Compose), Alembic migrations |
| Realtime | WebSocket connection manager (vitals + case-event + GPS streams) |
| Auth | PyJWT (bearer tokens), bcrypt password hashing |
| Frontend (Phase 1) | Vanilla JS/HTML/CSS served by FastAPI static mount |
| Maps | Leaflet + shared `medha/route.js` (OSRM with offline fallback) |
| Voice/AI | Web Speech API (SpeechRecognition + SpeechSynthesis) — Chrome/Edge |
| Interop | FHIR R4 bundles + CDA R2-style XML (LOINC / UCUM codes) |
| Sync | Hybrid logical clocks (HLC), pull/push change API |
| Testing | pytest + httpx, headless Node contract harnesses (`tests/js/*.cjs`) |
| Infra | Docker Compose (PostgreSQL 16), Uvicorn |

---

## Repository structure

```text
medha-link/
├── backend/                          # FastAPI application
│   ├── app/
│   │   ├── models/                   # SQLAlchemy models (11 tables, see below)
│   │   ├── routes/                   # API routers (auth, cases, ecg, handover, sync, …)
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── services/                 # Business logic (lifecycle, ETA, handover, sync, …)
│   │   ├── dependencies.py           # Auth / role / DB dependency injection
│   │   ├── database.py               # Engine, session factory, Base
│   │   └── static/                   # Phase-1 UI + shared assets
│   │       ├── ambulance-simulator/  # Ambulance client UI (+ device simulator)
│   │       ├── hospital-dashboard/   # Hospital client UI
│   │       ├── vendor/               # Leaflet + shared medha/route.js
│   │       ├── assistant.css         # MEDHA AI assistant styling
│   │       ├── assistant.js          # MEDHA AI intent engine (rules → fill/action/reply)
│   │       └── voice.js              # Voice recognition, TTS, fill/action dispatch
│   ├── alembic/                      # Database migrations (7 revisions)
│   ├── tests/                        # pytest suite + Node contract harnesses
│   │   └── js/                       # Headless checks for route/ecg/handover/hlc/samples
│   ├── alembic.ini
│   └── requirements.txt
├── ai-engine/                        # Placeholder — ECG AI, camera/visual AI, voice engine
├── ambulance-app/                    # Placeholder — future ambulance client (mobile/web)
├── doctor-console/                   # Placeholder — future remote doctor console
├── hospital-dashboard/               # Placeholder — future hospital web app
├── docs/                             # Design docs, walkthroughs, hardware reference
├── docker-compose.yml                # PostgreSQL 16 for local development
├── .env.example                      # Environment template (never commit the real .env)
└── README.md
```

The four placeholder directories (`ai-engine`, `ambulance-app`, `doctor-console`, `hospital-dashboard`) hold only a README for now. Phase-1 UI lives in `backend/app/static/`; they become real apps in later phases.

---

## Data model

| Table | Purpose | Key fields |
| --- | --- | --- |
| `users` | Staff accounts | `username`, `email`, `password_hash`, `role`, `hospital_id` |
| `hospitals` | Destination hospitals | `name`, `city`, `latitude/longitude`, `capabilities` (JSONB) |
| `ambulances` | Vehicles + crew assignment | `vehicle_number`, `status`, `hospital_id`, `assigned_to_id` |
| `patients` | Casualty records | `name`, `age`, `sex`, `blood_type`, `medical_history` (JSONB) |
| `emergency_cases` | The encounter itself | `status`, `severity`, `acceptance_status`, `chief_complaint`, `hospital_id`, `route_geojson` (JSONB), `hlc` |
| `vitals` | Time-series observations | `heart_rate`, `spo2`, `systolic_bp`, `diastolic_bp`, `temperature`, `respiratory_rate`, `source`, `hlc` |
| `gps_points` | Position fixes per case | `latitude`, `longitude`, `recorded_at`, `hlc` |
| `case_events` | Immutable event log | `event_type`, `payload` (JSONB with before/after changes) |
| `ecg_tracings` | Digitized ECGs | `source`, `lead_count`, `paper_speed`, `image_original`, `image_normalized`, `waveform`, `quality` (JSONB) |
| `devices` | Registered field devices | `owner_id`, `label` |
| `alembic_version` | Migration state | managed by Alembic |

---

## Domain state machine

**Roles** — `paramedic` (owns cases in the field), `doctor` (hospital clinical staff), `hospital_admin` (accept/decline/prepare + hospital management).

**Case statuses**

| Status | Meaning |
| --- | --- |
| `active` | Case open; crew at scene or en route |
| `transporting` | `transport_start` recorded; destination hospital assigned |
| `at_hospital` | `hospital_arrival` recorded; handover in progress |
| `closed` | `case_closed` recorded; `closed_at` set |

**Allowed transitions** (forward-only, enforced by `services/case_lifecycle.py`)

| Event | Allowed from | Result |
| --- | --- | --- |
| `scene_arrival` | `active` | stays `active` |
| `transport_start` | `active` | → `transporting` (assigns destination hospital + route) |
| `hospital_arrival` | `transporting` | → `at_hospital` (ambulance → `available`) |
| `case_closed` | `active`, `transporting`, `at_hospital` | → `closed` (ambulance → `available`) |
| `severity_changed` | `active`, `transporting`, `at_hospital` | updates `severity` only |

**Ambulance statuses** — `available`, `en_route`, `transporting`, `offline`. Transitioning to `transporting` sets the ambulance `transporting`; arrival/closing returns it to `available`.

**Severity levels** — `low`, `moderate`, `high`, `critical`.

Every transition appends an immutable `case_events` row with the before/after payload, so a case's full history is always replayable.

---

## API reference

All REST routes live under `/api/v1` and require a `Bearer` JWT unless noted. Interactive docs: **Swagger** at `/docs`, **ReDoc** at `/redoc`.

### Auth (`/api/v1/auth`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/register` | Create a staff account |
| POST | `/login` | Obtain a JWT (`access_token`) |
| GET | `/me` | Current authenticated user |

### Directory (`/api/v1/hospitals`, `/ambulances`, `/patients`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/hospitals` | Register a hospital |
| GET | `/hospitals` | List hospitals |
| GET | `/ambulances/mine` | Current user's assigned ambulance |
| POST | `/patients` | Create a patient |
| GET | `/patients/{patient_id}` | Fetch a patient |

### Cases (`/api/v1/cases`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/cases` | Create a case |
| GET | `/cases` | List cases (scoped by role) |
| GET | `/cases/{case_id}` | Fetch one case (with ETA) |
| POST | `/cases/{case_id}/transitions` | Apply a lifecycle event (see state machine) |
| GET | `/cases/{case_id}/events` | Case event log |
| GET | `/cases/{case_id}/gps` | GPS fix history |
| POST | `/cases/{case_id}/gps` | Record a GPS fix |
| POST | `/cases/{case_id}/accept` | Hospital accepts the case |
| POST | `/cases/{case_id}/decline` | Hospital declines (fallback nearest hospital) |
| POST | `/cases/{case_id}/prepare` | Hospital records preparation |

### Vitals (`/api/v1/cases`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/cases/{case_id}/vitals` | Post a vitals observation |
| GET | `/cases/{case_id}/vitals` | Query vitals history |

### ECG (`/api/v1/cases`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/cases/{case_id}/ecg` | Upload a digitized ECG (with waveform) |
| GET | `/cases/{case_id}/ecg` | List tracings for a case |
| GET | `/cases/{case_id}/ecg/{ecg_id}` | Fetch one tracing |
| GET | `/cases/{case_id}/ecg/{ecg_id}/image` | Fetch the normalized image |

### Handover (`/api/v1/cases`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/cases/{case_id}/handover` | Export handover — `?format=fhir` (default, `application/fhir+json`) or `?format=cda` (`text/xml`) |

### Sync (`/api/v1`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/devices` | Register a field device |
| POST | `/sync/push` | Apply an offline batch (vitals/events/gps) and broadcast |
| GET | `/sync/changes` | Pull changes since an HLC timestamp, filterable by `entity` / `case_id` |

### WebSocket (`/ws/...`)

| Path | Purpose |
| --- | --- |
| `/ws/cases/{case_id}/vitals` | Live vitals stream (auth via `?token=` or `Sec-WebSocket-Protocol`) |
| `/ws/cases/{case_id}/events` | Live case-event + GPS stream |

---

## WebSocket realtime

Connect with the JWT as a query param (`wss://host/ws/cases/{id}/vitals?token=…`) or a subprotocol. The server broadcasts to **all** clients subscribed to a case — the paramedic's publisher and the hospital viewers all share one stream.

- **Vitals stream** — each observation arrives as a JSON vitals payload; the dashboard appends it to the live chart.
- **Events stream** — carries serialized case state (`Event: case_update`) plus GPS fixes; after any REST or sync write the same payload is broadcast, so all screens reconcile without polling.

`ws.py` handles token extraction, origin/protocol negotiation, disconnect cleanup, and heartbeat ping.

---

## MEDHA AI assistant

A bilingual (English / Hindi) assistant is embedded in both Phase-1 UIs. Open it with the **🤖** floating button, then chat by typing or by voice (click the 🎙 mic).

**What it can do**

- **Fill forms from speech/text** — patient name, age, sex, chief complaint, and severity are extracted, applied to the form, and highlighted with a flash.
- **Trigger actions** — create case, start monitoring, digitize & send ECG (ambulance); accept case, prepare bed, refresh queue (hospital).
- **Answer live-state questions** — e.g. "What is the ETA?", "What is the patient's name?" — answered from the current case state.
- **Read replies aloud** — enable the 🔊 TTS toggle for spoken responses (en-IN / hi-IN).

**Try it (ambulance screen)**

```text
"name Ramesh age 45 male chest pain high severity"
"start monitoring"
"digitize and send ECG"
"what is the ETA?"
```

**Try it (hospital screen)**

```text
"accept case"
"prepare bed"
"refresh queue"
```

> **Browser support:** voice input uses the Web Speech API (SpeechRecognition) and works in Chrome/Edge. In Firefox/Safari the mic buttons are automatically disabled and text chat still works. Hindi (hi-IN) and English (en-IN) are both supported.

---

## Getting started

### Prerequisites

- **Docker** (with Compose) — for PostgreSQL 16
- **Python 3.11+**
- **Node.js 18+** — optional, only needed for the headless JS contract tests
- `psql` client (optional, for quick DB checks)

### 1. Clone and configure

```bash
git clone <repo-url> medha-link
cd medha-link
```

Copy the environment template and fill in the values (the defaults below already match `docker-compose.yml`):

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

```dotenv
# .env
POSTGRES_USER=medha
POSTGRES_PASSWORD=medha_dev_pw
POSTGRES_DB=medha_link
POSTGRES_PORT=5433
DATABASE_URL=postgresql+psycopg://medha:medha_dev_pw@localhost:5433/medha_link
JWT_SECRET=change_me_to_a_long_random_string
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

### 2. Start the database

```bash
docker compose up -d
docker compose ps
```

Quick connectivity check:

```bash
psql -h localhost -p 5433 -U medha -d medha_link -c "SELECT 1;"
```

### 3. Install the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  — or: source .venv/bin/activate (macOS/Linux)
pip install -r requirements.txt
```

### 4. Apply database migrations

```bash
alembic upgrade head
```

### 5. Seed development data

```bash
python -m app.seed_dev
```

Creates (idempotently): users `paramedic1`, `doctor1`, `admin1` (all password `s3curepass`), hospital `MEDHA City Hospital`, and ambulance `MH-01-AMB-001` assigned to `paramedic1`.

> Local development only — never reuse these credentials in production.

### 6. Run the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 7. Open the Phase-1 UI

| Screen | URL |
| --- | --- |
| Ambulance simulator | http://127.0.0.1:8000/ambulance-simulator/ |
| Hospital dashboard | http://127.0.0.1:8000/hospital-dashboard/ |
| API docs (Swagger) | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| Health check | http://127.0.0.1:8000/health |

---

## Environment variables

| Variable | Description | Default in compose |
| --- | --- | --- |
| `POSTGRES_USER` | PostgreSQL user | `medha` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `medha_dev_pw` |
| `POSTGRES_DB` | PostgreSQL database name | `medha_link` |
| `POSTGRES_PORT` | Host port mapped to 5432 | `5433` |
| `DATABASE_URL` | SQLAlchemy URL used by the app | `postgresql+psycopg://…:5433/medha_link` |
| `JWT_SECRET` | Signing key for access tokens | — (set a long random string) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes | `60` |

---

## Demo access

Use the seeded credentials:

| Role | Username | Password |
| --- | --- | --- |
| Paramedic | `paramedic1` | `s3curepass` |
| Doctor | `doctor1` | `s3curepass` |
| Hospital admin | `admin1` | `s3curepass` |

**Suggested demo flow**

1. Log in to the **ambulance simulator** as `paramedic1`.
2. Create a patient and case, then start monitoring — vitals stream in real time.
3. Log in to the **hospital dashboard** as `doctor1` or `admin1` and watch the case appear with live vitals.
4. **Accept** the case, **prepare a bed**, and complete the digital **handover** on arrival.
5. Try the **MEDHA AI assistant** on either screen (see above).

---

## Testing

### Backend (pytest)

```bash
cd backend
.venv\Scripts\activate        # Windows — or: source .venv/bin/activate
pytest -q
```

The suite covers auth, cases/lifecycle transitions, vitals + realtime, ECG, handover, sync, route mapping, resource roles, and the full end-to-end demo flow. Tests use `httpx` against the app; the database must be running.

```text
tests/
├── test_auth.py            # register / login / me / role scoping
├── test_ambulance.py       # ambulance ownership + status
├── test_cases (lifecycle)  # transitions, accept/decline/prepare, 409s
├── test_vitals + realtime  # vitals CRUD + WebSocket streams
├── test_ecg.py             # digitization upload + retrieval
├── test_handover.py        # FHIR / CDA export + access rules
├── test_sync.py            # push/pull queues + HLC ordering
├── test_route_map.py       # route / ETA / nearest-hospital
├── test_dashboard.py       # hospital queue + live updates
├── test_simulator.py       # ambulance simulator behavior
├── test_full_demo.py       # end-to-end seeded workflow
└── test_js_*.py            # Node contract harness bridges
```

### JS contract tests (Node)

The shared browser modules (`route.js`, ECG processing, handover/HLC helpers) are contract-tested headlessly against fixed sample inputs:

```bash
cd backend
pytest -q tests/test_js_route.py tests/test_js_ecg.py tests/test_js_handover.py tests/test_js_hlc.py tests/test_js_samples.py
```

These are skipped automatically when `node` is not installed.

---

## Documentation

Walkthroughs and research artifacts live in `docs/`:

| Document | What it covers |
| --- | --- |
| `ecg-quality-walkthrough.md` | Manual acceptance checklist for the paper-ECG digitization pipeline |
| `handover-walkthrough.md` | Manual acceptance checklist for dashboard handover + FHIR / CDA / PDF export |
| `phase2-research.md` | Phase-2 research & architecture review (source findings vs. proposals vs. inferences) |
| `medha-link-hardware-v1` (HTML/PDF) | Hardware reference for the Phase-1 ambulance device kit |

---

## Project status & roadmap

**Phase 1 — complete** (monorepo build-out):

- [x] Infrastructure — Docker + PostgreSQL 16
- [x] FastAPI backend, models, and Alembic migrations
- [x] JWT auth with `paramedic` / `doctor` / `hospital_admin` roles
- [x] Patient / case / vitals APIs + WebSocket realtime
- [x] Encounter lifecycle and hospital transport coordination
- [x] Offline-first sync layer (HLC-ordered)
- [x] Ambulance simulator + hospital dashboard (Phase-1 UI)
- [x] Route mapping (Leaflet + OSRM with offline fallback)
- [x] GPS tracking + ETA (routed polyline with haversine fallback)
- [x] Paper ECG digitization with sync and dashboard viewer
- [x] Digital handover with FHIR R4 + CDA export and vitals replay
- [x] MEDHA AI assistant (voice/text, bilingual, TTS)
- [x] End-to-end tests (pytest + Node contract harnesses)

**Later phases (planned)**

- ECG AI classification + paper-ECG image pipeline
- MEDHA Voice server-side engine (no browser dependency)
- Camera/visual assessment and remote doctor video
- Hospital capability matching and pre-arrival preparation
- Real IoT device integration
- Mobile/web apps graduating the placeholder directories

---

## FAQ

**Is this production-ready for real patients?** No. It is a research prototype. All data is synthetic, ECGs make no diagnostic interpretation, and every exported handover carries an explicit research-prototype boundary statement.

**What is "HLB/HLC"?** Each synced row carries a hybrid logical clock (`hlc`) so offline clients can order changes deterministically and the sync layer can skip stale or already-applied operations.

**Which browser do the UIs target?** Voice input needs the Web Speech API (Chrome/Edge). The rest of the UI works in any modern browser; mic buttons auto-disable where unsupported.

**How is the ETA computed?** If the case has a routed polyline (`route_geojson`), the remaining journey is the route duration scaled by how far along it the latest GPS fix has traveled; otherwise a straight-line haversine distance at 30 km/h. Both are explicitly prototype calculations.

**Where does the Phase-1 UI live?** In `backend/app/static/` — it is served by FastAPI. The top-level `ambulance-app/`, `hospital-dashboard/`, `doctor-console/`, and `ai-engine/` directories are placeholders for future standalone apps.

---

## License

Proprietary — not yet published under an open-source license. All patient data is synthetic and for local development/testing only. Contact the maintainers for reuse or contribution.
