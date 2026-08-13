<div align="center">

<!-- MEDHA LINK — 3D extruded wordmark with ECG pulse (inline SVG, no external files) -->
<svg viewBox="0 0 1200 320" width="720" height="auto" role="img" aria-label="MEDHA LINK" xmlns="http://www.w3.org/2000/svg">
  <title>MEDHA LINK</title>
  <defs>
    <linearGradient id="gradMedha" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#eaf5ff"/>
      <stop offset="0.22" stop-color="#9fc8ff"/>
      <stop offset="0.6" stop-color="#3a78e8"/>
      <stop offset="1" stop-color="#1e3a8a"/>
    </linearGradient>
    <linearGradient id="gradLink" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#d5f8ff"/>
      <stop offset="0.45" stop-color="#4fd1f0"/>
      <stop offset="1" stop-color="#0b7285"/>
    </linearGradient>
    <linearGradient id="gradPulse" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fca5a5"/>
      <stop offset="0.5" stop-color="#ef4444"/>
      <stop offset="1" stop-color="#b91c1c"/>
    </linearGradient>
  </defs>

  <!-- ECG trace (double-stroked for a soft glow, no filters) -->
  <g>
    <polyline points="90,276 500,276 520,268 540,257 556,276 578,276 594,260 608,240 622,276 642,276 656,264 670,276 1110,276"
              fill="none" stroke="#ef4444" stroke-opacity="0.3" stroke-width="14"
              stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="90,276 500,276 520,268 540,257 556,276 578,276 594,260 608,240 622,276 642,276 656,264 670,276 1110,276"
              fill="none" stroke="url(#gradPulse)" stroke-width="4.5"
              stroke-linejoin="round" stroke-linecap="round"
              stroke-dasharray="1120">
      <animate attributeName="stroke-dashoffset" from="1120" to="0" dur="3s" fill="freeze"/>
    </polyline>
    <circle cx="608" cy="240" r="11" fill="#ef4444" opacity="0.25"/>
    <circle cx="608" cy="240" r="6" fill="#f87171">
      <animate attributeName="r" values="4.5;7;4.5" dur="1.6s" repeatCount="indefinite"/>
    </circle>
  </g>

  <!-- MEDHA — extruded depth (dark base -> lighter toward the face) -->
  <g transform="translate(600,132)" font-family="system-ui, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif" font-size="132" font-weight="800" letter-spacing="6" text-anchor="middle">
    <text transform="translate(0,22)" fill="#040b18">MEDHA</text>
    <text transform="translate(0,20)" fill="#061126">MEDHA</text>
    <text transform="translate(0,18)" fill="#081833">MEDHA</text>
    <text transform="translate(0,16)" fill="#0a1f41">MEDHA</text>
    <text transform="translate(0,14)" fill="#0c264f">MEDHA</text>
    <text transform="translate(0,12)" fill="#0e2d5d">MEDHA</text>
    <text transform="translate(0,10)" fill="#10346b">MEDHA</text>
    <text transform="translate(0,8)" fill="#123b79">MEDHA</text>
    <text transform="translate(0,6)" fill="#144287">MEDHA</text>
    <text transform="translate(0,4)" fill="#164995">MEDHA</text>
    <text transform="translate(0,2)" fill="#1850a3">MEDHA</text>
    <text fill="url(#gradMedha)">MEDHA</text>
  </g>

  <!-- LINK — extruded depth -->
  <g transform="translate(600,240)" font-family="system-ui, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif" font-size="74" font-weight="800" letter-spacing="16" text-anchor="middle">
    <text transform="translate(0,20)" fill="#02141f">LINK</text>
    <text transform="translate(0,18)" fill="#041d2b">LINK</text>
    <text transform="translate(0,16)" fill="#062638">LINK</text>
    <text transform="translate(0,14)" fill="#082f45">LINK</text>
    <text transform="translate(0,12)" fill="#0a3852">LINK</text>
    <text transform="translate(0,10)" fill="#0c415f">LINK</text>
    <text transform="translate(0,8)" fill="#0e4a6c">LINK</text>
    <text transform="translate(0,6)" fill="#105379">LINK</text>
    <text transform="translate(0,4)" fill="#125c86">LINK</text>
    <text transform="translate(0,2)" fill="#146593">LINK</text>
    <text fill="url(#gradLink)">LINK</text>
  </g>
</svg>

**Real-time emergency response and pre-hospital care coordination — from the ambulance to the hospital bed, live.**

</div>

---

## Overview

MEDHA LINK keeps everyone on the same page during an emergency: the paramedic in the ambulance, the hospital staff waiting at the other end, and the doctors coordinating the response.

1. A **paramedic** creates a patient encounter and starts streaming vitals from the ambulance simulator.
2. The **hospital dashboard** sees the case instantly — live vitals, deterioration alerts, no refresh required.
3. A **doctor or hospital admin** accepts, declines, or prepares for the case before the ambulance arrives.
4. When the crew gets there, a structured digital **handover** (FHIR R4 / CDA export optional) closes the loop.

Everything runs on a FastAPI backend with PostgreSQL, WebSocket realtime, and an offline-first sync layer. New in Phase 1: a bilingual voice + text **AI assistant** lives right inside both UIs.

> **Heads up — synthetic data only.** Everything here is generated locally for development and testing. Never use it with real patient information.

---

## Key features

- **Live vitals** — heart rate, SpO₂, blood pressure, temperature, and respiration stream from the ambulance to the hospital over WebSocket; deterioration surfaces the moment it happens.
- **Encounter lifecycle** — cases move through created → assigned → en route → arrived → handover complete via `accept`, `decline`, `prepare`, and transition endpoints.
- **Paper ECG digitization** — capture the tracing offline, extract it, sync it to the backend, and view it on the hospital dashboard.
- **Route & mapping** — a shared geometry engine (`medha/route.js`): haversine distances, polyline interpolation, OSRM routing with an offline straight-line fallback, drawn on a Leaflet map.
- **Digital handover** — a structured record with vitals replay, exportable as a **FHIR R4 bundle** or **CDA XML**.
- **Offline-first sync** — pull/push queues let clients work disconnected and reconcile when they reconnect.
- **Auth & roles** — JWT bearer auth with `paramedic`, `doctor`, and `hospital_admin` roles.
- **MEDHA AI assistant** — bilingual (en-IN / hi-IN) voice + text; fills patient and case forms, triggers actions, answers live-state questions, and reads replies aloud.

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

## Tech stack

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

## Repository structure

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

The four placeholder directories (`ai-engine`, `ambulance-app`, `doctor-console`, `hospital-dashboard`) hold only a README for now. Phase-1 UI lives in `backend/app/static/`; they'll become real apps in later phases.

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
| Health check | http://127.0.0.1:8000/health |

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
5. Try the **MEDHA AI assistant** on either screen (see below).

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

## API documentation

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

## Project status & roadmap

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
