from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .database import engine
from .routes import ambulances, auth, cases, hospitals, patients, sync, vitals, ws

app = FastAPI(title="MEDHA LINK Backend", version="0.1.0")

app.include_router(auth.router)
app.include_router(hospitals.router)
app.include_router(patients.router)
app.include_router(ambulances.router)
app.include_router(cases.router)
app.include_router(vitals.router)
app.include_router(sync.router)
app.include_router(ws.router)


@app.get("/health")
def health() -> JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": f"error: {exc}"},
        )
    return JSONResponse(content={"status": "ok", "database": "connected"})


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
