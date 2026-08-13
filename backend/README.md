# MEDHA LINK — Backend

FastAPI backend for MEDHA LINK: real-time emergency response and pre-hospital care coordination. See the [root README](../README.md) for the full project overview, setup, and demo flow.

## Stack

- Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2
- PostgreSQL 16 (Docker Compose) with Alembic migrations
- JWT auth (PyJWT) + bcrypt, WebSocket realtime, offline-first sync
- Serves the Phase-1 UIs (ambulance simulator + hospital dashboard) from `app/static/`

## Layout

```text
backend/
├── app/
│   ├── models/        # SQLAlchemy models
│   ├── routes/        # FastAPI routers (auth, cases, ecg, handover, sync, vitals, ws, …)
│   ├── schemas/       # Pydantic schemas
│   ├── services/      # Business logic (case lifecycle, ETA, realtime, sync, …)
│   ├── config.py      # Settings (reads ../.env at repo root)
│   ├── database.py    # SQLAlchemy engine/session
│   └── static/        # Phase-1 UI + shared assets (incl. MEDHA AI assistant)
├── alembic/           # Database migrations
├── tests/             # pytest suite + Node contract harnesses (tests/js/*.cjs)
├── alembic.ini
└── requirements.txt
```

## Quick start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows — or: source .venv/bin/activate (macOS/Linux)
pip install -r requirements.txt

alembic upgrade head          # apply migrations
python -m app.seed_dev        # seed demo users, hospital, ambulance
uvicorn app.main:app --reload --port 8000
```

Requires the PostgreSQL container from the repo root: `docker compose up -d`.

## Configuration

Settings are read from the `.env` file at the repository root (see `.env.example`). Required values: `DATABASE_URL` and `JWT_SECRET`.

## API docs

- Swagger UI — http://127.0.0.1:8000/docs
- ReDoc — http://127.0.0.1:8000/redoc
- Health — http://127.0.0.1:8000/health

## Testing

```bash
pytest -q
```

The JS contract tests (`tests/test_js_*.py`) run headless Node harnesses from `tests/js/` and are skipped automatically if Node is unavailable.
