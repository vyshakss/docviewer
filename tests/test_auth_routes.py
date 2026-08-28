# tests/test_auth_routes.py
import pyotp
from fastapi.testclient import TestClient


def _setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    settings = get_settings()
    db.init_db(settings.db_path)

    from app.auth import models
    from app.auth.security import generate_totp_secret

    secret = generate_totp_secret()
    models.create_user("vyshak", "correct horse battery staple", secret)

    from app.main import app
    # base_url must be https:// so the httpx-backed TestClient's cookie jar
    # will store and replay the Secure-flagged session cookies our routes set
    # (login/logout deal in real session tokens and must stay Secure=True).
    return TestClient(app, base_url="https://testserver"), secret


def test_login_flow_success(tmp_path, monkeypatch):
    client, secret = _setup_app(tmp_path, monkeypatch)

    resp = client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    assert resp.status_code == 200
    assert resp.json()["requires_totp"] is True
    assert "pending_token" in client.cookies

    code = pyotp.TOTP(secret).now()
    resp = client.post("/login/verify", json={"code": code})
    assert resp.status_code == 200
    assert "session_token" in client.cookies


def test_login_wrong_password(tmp_path, monkeypatch):
    client, _secret = _setup_app(tmp_path, monkeypatch)

    resp = client.post("/login", json={"username": "vyshak", "password": "wrong"})
    assert resp.status_code == 401
    assert "pending_token" not in client.cookies


def test_login_lockout_after_repeated_failures(tmp_path, monkeypatch):
    client, _secret = _setup_app(tmp_path, monkeypatch)

    for _ in range(5):
        client.post("/login", json={"username": "vyshak", "password": "wrong"})

    resp = client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    assert resp.status_code == 429


def test_login_verify_wrong_code(tmp_path, monkeypatch):
    client, _secret = _setup_app(tmp_path, monkeypatch)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    resp = client.post("/login/verify", json={"code": "000000"})
    assert resp.status_code == 401
    assert "session_token" not in client.cookies


def test_login_verify_lockout_after_repeated_totp_failures(tmp_path, monkeypatch):
    client, secret = _setup_app(tmp_path, monkeypatch)

    for _ in range(5):
        resp = client.post(
            "/login", json={"username": "vyshak", "password": "correct horse battery staple"}
        )
        assert resp.status_code == 200
        resp = client.post("/login/verify", json={"code": "000000"})
        assert resp.status_code == 401

    resp = client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    assert resp.status_code == 429


def test_logout_clears_session(tmp_path, monkeypatch):
    client, secret = _setup_app(tmp_path, monkeypatch)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})
    session_token = client.cookies["session_token"]

    resp = client.post("/logout", headers={"X-CSRF-Token": client.cookies["csrf_token"]})
    assert resp.status_code == 200

    # The session must actually be invalidated server-side, not just have its
    # cookie cleared client-side: replay the (still-known) session cookie
    # value directly against a protected route and confirm it's rejected.
    resp = client.get("/app", headers={"Cookie": f"session_token={session_token}"})
    assert resp.status_code == 401


def test_expired_session_rejected_at_route_level(tmp_path, monkeypatch):
    # Task 4 covers session expiry at the model level (models.get_session
    # returns None past expires_at). This confirms the same behavior holds
    # end-to-end through an actual protected route, not just the model layer.
    client, _secret = _setup_app(tmp_path, monkeypatch)

    from app.auth import models

    user = models.get_user_by_username("vyshak")
    expired_token, _csrf = models.create_session(user["id"], ttl_seconds=-1)

    resp = client.get("/app", headers={"Cookie": f"session_token={expired_token}"})
    assert resp.status_code == 401


def test_logout_requires_csrf(tmp_path, monkeypatch):
    client, secret = _setup_app(tmp_path, monkeypatch)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    resp = client.post("/logout")
    assert resp.status_code == 403
    # session must remain valid since logout without CSRF must not succeed
    assert "session_token" in client.cookies
