from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import CurrentUser, require_role
from app.models import User
from app.models.enums import UserRole
from app.security import create_access_token


@pytest.fixture()
def make_user(client):
    def _make(role: UserRole, idx: int = 0):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": f"{role.value}{idx}",
                "email": f"{role.value}{idx}@example.com",
                "password": "s3curepass",
                "role": role.value,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


def test_register_three_roles(client, make_user):
    for role, idx in [
        (UserRole.paramedic, 0),
        (UserRole.doctor, 0),
        (UserRole.hospital_admin, 0),
    ]:
        body = make_user(role, idx)
        assert body["role"] == role.value
        assert "password_hash" not in body


def test_register_duplicate_username_conflict(client, make_user):
    make_user(UserRole.paramedic, 0)
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": "paramedic0",
            "email": "other@example.com",
            "password": "s3curepass",
            "role": "paramedic",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Username already registered"


def test_register_duplicate_email_conflict(client, make_user):
    make_user(UserRole.doctor, 0)
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": "someone-else",
            "email": "doctor0@example.com",
            "password": "s3curepass",
            "role": "doctor",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already registered"


def test_password_is_hashed_not_plaintext(make_user):
    from app.database import SessionLocal
    from app.models import User
    from app.security import verify_password

    make_user(UserRole.paramedic, 0)
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="paramedic0").one()
    finally:
        db.close()
    assert user.password_hash != "s3curepass"
    assert "s3curepass" not in user.password_hash
    assert verify_password("s3curepass", user.password_hash) is True
    assert verify_password("wrong", user.password_hash) is False


def test_login_success_returns_jwt(client, make_user):
    make_user(UserRole.paramedic, 0)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "paramedic0", "password": "s3curepass"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "paramedic0"


def test_login_wrong_password_401(client, make_user):
    make_user(UserRole.paramedic, 0)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "paramedic0", "password": "wrongpass"},
    )
    assert resp.status_code == 401


def test_missing_token_401(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_invalid_token_401(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


def test_expired_token_401(client):
    token = create_access_token(
        subject="00000000-0000-0000-0000-000000000000",
        role=UserRole.paramedic,
        expires_delta=timedelta(minutes=-5),
    )
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


auth_router = APIRouter()


@auth_router.get("/test-protected")
def protected(current_user: CurrentUser):
    return {"user": current_user.username}


@auth_router.get("/test-hospital-admin")
def hospital_only(
    current_user: User = Depends(require_role(UserRole.hospital_admin)),
):
    return {"user": current_user.username}


def _test_app_for_roles() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(auth_router)
    return test_app


def _make_role_client():
    from fastapi.testclient import TestClient

    return TestClient(_test_app_for_roles())


def test_role_allowed(client, make_user):
    make_user(UserRole.hospital_admin, 0)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "hospital_admin0", "password": "s3curepass"},
    ).json()
    token = login["access_token"]

    role_client = _make_role_client()
    resp = role_client.get(
        "/test-hospital-admin", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"] == "hospital_admin0"


def test_role_forbidden(client, make_user):
    make_user(UserRole.paramedic, 0)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "paramedic0", "password": "s3curepass"},
    ).json()
    token = login["access_token"]

    role_client = _make_role_client()
    resp = role_client.get(
        "/test-hospital-admin", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_jwt_contains_only_intended_claims(client, make_user):
    import jwt

    from app.config import settings

    make_user(UserRole.doctor, 0)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "doctor0", "password": "s3curepass"},
    ).json()
    payload = jwt.decode(
        login["access_token"], settings.jwt_secret, algorithms=["HS256"]
    )
    assert set(payload.keys()) == {"sub", "role", "iat", "exp"}
    assert payload["role"] == "doctor"
