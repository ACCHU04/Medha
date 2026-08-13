# MEDHA LINK

Real-time emergency response and pre-hospital care coordination platform that connects ambulances, hospital staff, and doctors around a single, continuously-updated patient encounter.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![WebSocket](https://img.shields.io/badge/Realtime-WebSocket-4F46E5)
![JWT](https://img.shields.io/badge/Auth-JWT%20Bearer-E0234E)
![License](https://img.shields.io/badge/License-Proprietary-lightgrey)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Demo Access](#demo-access)
- [MEDHA AI Assistant](#medha-ai-assistant)
- [Testing](#testing)
- [API Documentation](#api-documentation)
- [Project Status & Roadmap](#project-status--roadmap)
- [License](#license)

---

## Overview

MEDHA LINK is a single command-and-control workflow for emergency medical response:

1. A **paramedic** creates a patient encounter in the ambulance simulator and starts streaming vitals.
2. The **hospital dashboard** sees the case and live vitals in real time, with deterioration events surfacing immediately.
3. A **doctor or hospital admin** can accept, decline, or prepare for the case before arrival.
4. On arrival, a structured digital **handover** (with optional FHIR R4 / CDA export) closes the loop.

The entire loop is driven by a FastAPI backend with PostgreSQL persistence, WebSocket realtime, an offline-first sync layer, and — new in Phase 1 — a bilingual voice/text **AI assistant** embedded directly in both web UIs.

> **Synthetic data only.** All patient data is generated locally for development and testing. Never use with real patient information.

---

## Key Features

| Area | What it does |
| --- | --- |
| **Realtime vitals** | Paramedic streams heart rate, SpO₂, blood pressure, temperature, and respiration rate; hospital dashboard updates live over WebSocket and flags deterioration. |
| **Encounter lifecycle** | Cases move through states — created → assigned → en route → arrived → handover complete — via `accept`, `decline`, `prepare`, and transition endpoints. |
| **Paper ECG digitization** | Offline image capture, AI-assisted extraction of the ECG tracing, sync to backend, and viewing on the hospital dashboard. |
| **Route & mapping** | Shared geometry engine (`medha/route.js`): haversine distances, polyline interpolation, OSRM routing with an offline straight-line fallback, rendered on a Leaflet map. |
| **Digital handover** | Structured handover record with vitals replay, plus export as a **FHIR R4 bundle** or **CDA XML** (NABH-aligned). |
| **Offline-first sync** | Pull/push sync layer with operation queues so mobile clients can work disconnected and reconcile later. |
| **Auth & roles** | JWT bearer auth with `paramedic`, `doctor`, and `hospital_admin` roles. |
| **MEDHA AI assistant** | Voice (en-IN / hi-IN) and text assistant embedded in both UIs — fills patient/case forms, triggers actions, answers live-state questions, and reads replies aloud (TTS). |

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

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2 |
| Database | PostgreSQL 16 (Docker Compose), Alembic migrations |
| Realtime | WebSocket (vitals + case-event streams) |
| Auth | PyJWT (bearer tokens), bcrypt password hashing |
| Frontend (Phase 1) | Vanilla JS/HTML/CSS served by FastAPI static mount |
| Maps | Leaflet + shared `medha/route.js` (OSRM with offline fallback) |
| Voice/AI | Web Speech API (SpeechRecognition + SpeechSynthesis) — Chrome/Edge |
| Testing | pytest + httpx, headless Node contract harnesses (`tests/js/*.cjs`) |
| Infra | Docker Compose (PostgreSQL 16), Uvicorn |

---

## Repository Structure

```text
medha-link/
├── backend/                          # FastAPI application
│   ├── app/
│   │   ├── models/                   # SQLAlchemy models (patient, case, vital, ecg, hospital, …)
│   │   ├── routes/                   # API routers (auth, cases, ecg, handover, sync, vitals, ws, …)
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── services/                 # Business logic (case lifecycle, ETA, realtime, sync, …)
│   │   └── static/                   # Phase-1 UI + shared assets
│   │       ├── ambulance-simulator/  # Ambulance client UI
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

The four placeholder directories (`ai-engine`, `ambulance-app`, `doctor-console`, `hospital-dashboard`) hold only a README for now. Phase-1 UI lives in `backend/app/static/`; these directories graduate into real apps in later phases.

---

## Getting Started

### Prerequisites

- **Docker** (with Compose) — for PostgreSQL 16
- **Python 3.11+**
- **Node.js 18+** — optional, only required for the headless JS contract tests
- `psql` client (optional, for quick DB checks)

### 1. Clone and configure

```bash
git clone <repo-url> medha-link
cd medha-link
```

Copy the environment template and set the values (the defaults below match `docker-compose.yml`):

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
| Health check | http://127.0.0.1:8000/health |

---

## Demo Access

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
5. Try the **MEDHA AI assistant** on either screen (see below).

---

## MEDHA AI Assistant

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

## Testing

### Backend (pytest)

```bash
cd backend
.venv\Scripts\activate        # Windows — or: source .venv/bin/activate
pytest -q
```

The suite covers auth, cases/lifecycle transitions, vitals + realtime, ECG, handover, sync, route mapping, and the full end-to-end demo flow. Tests use `httpx` against the app; the database must be running.

### JS contract tests (Node)

The shared browser modules (`route.js`, ECG processing, handover/HLC helpers) are contract-tested headlessly:

```bash
cd backend
pytest -q tests/test_js_route.py tests/test_js_ecg.py tests/test_js_handover.py tests/test_js_hlc.py
```

These are skipped automatically when `node` is not installed.

---

## API Documentation

Interactive docs are served by FastAPI when the backend is running:

- **Swagger UI** — http://127.0.0.1:8000/docs
- **ReDoc** — http://127.0.0.1:8000/redoc
- **Health check** — http://127.0.0.1:8000/health

### Main API groups

| Group | Purpose |
| --- | --- |
| `/auth` | Register, login (JWT), current user |
| `/hospitals`, `/ambulances`, `/patients` | Directory + ownership |
| `/cases` | Case CRUD, transitions (accept/decline/prepare), events, GPS |
| `/vitals` | Post + query vitals per case |
| `/ecg` | Paper ECG digitization upload + retrieval |
| `/handover` | Digital handover record (+ FHIR/CDA export) |
| `/sync` | Offline pull/push sync |
| `/ws/cases/{id}/vitals`, `/ws/cases/{id}/events` | Realtime WebSocket streams |

---

## Project Status & Roadmap

**Phase 1 — complete** (monorepo build-out):

- [x] Infrastructure — Docker + PostgreSQL 16
- [x] FastAPI backend, models, and Alembic migrations
- [x] JWT auth with `paramedic` / `doctor` / `hospital_admin` roles
- [x] Patient / case / vitals APIs + WebSocket realtime
- [x] Encounter lifecycle and hospital transport coordination
- [x] Offline-first sync layer
- [x] Ambulance simulator + hospital dashboard (Phase-1 UI)
- [x] Route mapping (Leaflet + OSRM with offline fallback)
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

## License

Proprietary — not yet published under an open-source license. All patient data is synthetic and for local development/testing only. Contact the maintainers for reuse or contribution.
