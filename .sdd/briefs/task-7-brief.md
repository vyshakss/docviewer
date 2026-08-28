# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 7: Login, TOTP verify, and logout routes

**Files:**
- Create: `app/auth/routes.py`
- Modify: `app/main.py` (mount the auth router)
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `app.auth.models.*`, `app.auth.security.verify_password`, `app.auth.security.verify_totp`, `app.auth.dependencies.get_current_user`, `app.config.get_settings`.
- Produces: `app.auth.routes.router` (FastAPI `APIRouter`), routes `POST /login`, `POST /login/verify`, `POST /logout`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_routes.py
import pyotp
from fastapi.testclient import TestClient


def _setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

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
    return TestClient(app), secret


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


def test_logout_clears_session(tmp_path, monkeypatch):
    client, secret = _setup_app(tmp_path, monkeypatch)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    resp = client.post("/logout")
    assert resp.status_code == 200

    resp = client.get("/healthz")  # any route; check session no longer valid via whoami-like check
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.routes'`

- [ ] **Step 3: Write `app/auth/routes.py`**

```python
# app/auth/routes.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import models
from app.auth.dependencies import get_current_user
from app.auth.security import verify_password, verify_totp
from app.config import get_settings

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class VerifyBody(BaseModel):
    code: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    settings = get_settings()
    ip = _client_ip(request)

    if models.is_locked_out(
        body.username, ip, settings.login_lockout_threshold, settings.login_lockout_window_seconds
    ):
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later")

    user = models.get_user_by_username(body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        models.record_login_attempt(body.username, ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    models.record_login_attempt(body.username, ip, success=True)
    pending_token = models.create_pending_login(user["id"], settings.pending_login_ttl_seconds)

    response.set_cookie(
        "pending_token",
        pending_token,
        max_age=settings.pending_login_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return {"requires_totp": True}


@router.post("/login/verify")
def login_verify(body: VerifyBody, request: Request, response: Response):
    settings = get_settings()
    pending_token = request.cookies.get("pending_token")
    if pending_token is None:
        raise HTTPException(status_code=401, detail="No pending login")

    row = models.verify_and_bump_pending_login(pending_token, max_attempts=5)
    if row is None:
        response.delete_cookie("pending_token")
        raise HTTPException(status_code=401, detail="Pending login expired, please log in again")

    user = models.get_user_by_id(row["user_id"])
    if user is None or not verify_totp(user["totp_secret"], body.code):
        models.increment_pending_login_attempts(pending_token)
        raise HTTPException(status_code=401, detail="Invalid code")

    models.delete_pending_login(pending_token)
    session_token, csrf_token = models.create_session(user["id"], settings.session_ttl_seconds)

    response.delete_cookie("pending_token")
    response.set_cookie(
        "session_token",
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=True,
        samesite="strict",
    )
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(get_current_user)):
    raw_token = request.cookies.get("session_token")
    if raw_token:
        models.delete_session(raw_token)
    response.delete_cookie("session_token")
    response.delete_cookie("csrf_token")
    return {"ok": True}
```

- [ ] **Step 4: Mount the router in `app/main.py`**

```python
# add near the top of app/main.py
from app.auth.routes import router as auth_router

# add after `app = FastAPI(...)`
app.include_router(auth_router)


@app.on_event("startup")
def _startup() -> None:
    from app.config import get_settings
    from app.db import init_db

    init_db(get_settings().db_path)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_auth_routes.py -v`
Expected: PASS (5 tests)

