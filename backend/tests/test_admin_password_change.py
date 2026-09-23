"""Test suite for admin seed password change verification."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://care-rota-engine.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "manager@grizedale.local"
NEW_PASSWORD = "changeme123"
OLD_PASSWORD = "ChangeMe123!"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def test_login_new_password_success(session):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": NEW_PASSWORD})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    # Token can be under different keys
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    assert isinstance(token, str) and len(token) > 20
    user = data.get("user") or data
    assert user.get("password_must_change") is False, f"password_must_change should be False, got: {user.get('password_must_change')} - full: {data}"
    pytest.token = token


def test_login_old_password_fails(session):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": OLD_PASSWORD})
    assert r.status_code == 401, f"Expected 401 for old password, got {r.status_code}: {r.text}"


def test_auth_me_with_new_token(session):
    token = getattr(pytest, "token", None)
    assert token, "No token from login test"
    r = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"Expected 200 at /auth/me, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("email") == ADMIN_EMAIL, f"Email mismatch: {data}"
