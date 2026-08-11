import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = (
    "postgresql+psycopg://medha:medha_dev_pw@localhost:5433/medha_link_test"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import (
    Ambulance,
    CaseEvent,
    Device,
    EcgTracing,
    EmergencyCase,
    GpsPoint,
    Hospital,
    Patient,
    User,
    Vital,
)


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_db():
    env = dict(os.environ)
    env["DATABASE_URL"] = TEST_DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    yield


@pytest.fixture()
def client(_migrated_test_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_tables(_migrated_test_db):
    db = SessionLocal()
    try:
        for model in (
            CaseEvent,
            GpsPoint,
            Vital,
            EcgTracing,
            EmergencyCase,
            Ambulance,
            Patient,
            Device,
            User,
            Hospital,
        ):
            db.query(model).delete()
        db.commit()
    finally:
        db.close()
    yield
