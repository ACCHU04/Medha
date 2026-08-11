# MEDHA LINK

Real-time emergency response and pre-hospital care coordination platform.

## Architecture

```text
                 MEDHA LINK
                     |
       +-------------+-------------+
       |             |             |
       v             v             v
 Ambulance     Hospital      Doctor
   App         Dashboard     Console
       |             |             |
       +-------------+-------------+
                     v
                Backend (FastAPI)
                     |
          +----------+----------+
          v          v          v
     PostgreSQL    AI Engine   Realtime (WebSocket)
```

## Repository layout

```text
medha-link/
|-- backend/            FastAPI app, models, routes, services, tests, Phase-1 static UI
|-- ambulance-app/      future-facing (mobile/web ambulance client) - placeholder
|-- hospital-dashboard/ future-facing (hospital web app) - placeholder
|-- doctor-console/     future-facing (doctor console) - placeholder
|-- ai-engine/          future-facing (ECG AI, camera AI, voice) - placeholder
|-- docs/               design docs (data model, roadmap)
|-- docker-compose.yml  PostgreSQL 16 for local development
|-- .env                local dev secrets (git-ignored)
`-- .env.example        template with placeholders only
```

## Phase 1 goal

**Paramedic creates a simulated emergency -> ambulance simulator streams vitals -> hospital dashboard sees them live -> deterioration triggers -> hospital immediately sees the critical change.**

Phase-1 UI lives in `backend/app/static/`; the top-level app directories stay as placeholders until they graduate to real apps.

## Local development

### Prerequisites

- Docker (with Compose)
- Python 3.11+
- psql client (optional, for quick DB checks)

### 1. Start the database

```bash
docker compose up -d
docker compose ps
```

### 2. Verify connectivity

```bash
psql -h localhost -p 5433 -U medha -d medha_link -c "SELECT 1;"
```

### 3. Run the backend (from Step 2 onward)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Migrations (from Step 3 onward)

```bash
alembic upgrade head
```

### 5. Seed development data (from Step 7 onward)

```bash
python -m app.seed_dev
```

Creates (idempotently): `paramedic1`, `doctor1`, `admin1` (all password `s3curepass`), hospital `MEDHA City Hospital`, and ambulance `MH-01-AMB-001` (status `transporting`) assigned to `paramedic1`. Local development only; never reuse these credentials in production.

### 6. Phase-1 UI

```bash
# ambulance simulator (Step 7)
http://127.0.0.1:8000/ambulance-simulator/   # login: paramedic1 / s3curepass
# hospital dashboard (Step 8)
http://127.0.0.1:8000/hospital-dashboard/
```

## Build roadmap

1. Infrastructure (Docker + PostgreSQL) - DONE
2. FastAPI + DB connection
3. Models + Alembic
4. JWT authentication (roles: paramedic / doctor / hospital_admin)
5. Patient / case / vitals APIs
6. WebSocket realtime
7. Ambulance simulator (simulated vitals)
8. Hospital dashboard
9. E2E tests
10. Full demo (create patient -> stream vitals -> deterioration)

Later phases: ECG + paper ECG digitization + ECG AI, MEDHA Voice, camera/visual assessment, remote doctor video, hospital capability matching, pre-arrival preparation, digital handover, real IoT integration.

## Synthetic data only

All patient data is synthetic and for local development/testing only.
