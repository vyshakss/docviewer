# docviewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight, self-hosted, single-user, TOTP-protected web app to browse/preview/manage PDF, docx, and text/code/markdown files on the Fedora server, deployable as one rootless Podman container.

**Architecture:** One FastAPI app serving a JSON API plus a small vanilla-JS frontend. SQLite (users/sessions/login attempts) is the only database; the filesystem (a bind-mounted host directory) is the source of truth for files. Docx/doc preview goes through a LibreOffice-headless subprocess conversion to PDF, cached on disk, then rendered client-side with PDF.js. Text/code/markdown render client-side from raw bytes — no server conversion.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLite (stdlib `sqlite3`), argon2-cffi, pyotp, LibreOffice headless (via subprocess), PDF.js + highlight.js + marked.js (vendored at build time), Podman + systemd Quadlet.

**Spec:** `docs/superpowers/specs/2026-08-25-docviewer-design.md`

**No git.** Do not run any `git` commands as part of this plan — the user explicitly does not want git used for this project. Every task ends after its tests pass; skip any "commit" step.

## Global Constraints

- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

## File Structure

```
docviewer/
  app/
    __init__.py
    main.py                 # FastAPI app, routers, security headers, static mount
    config.py                # Settings (env-driven)
    db.py                    # SQLite connection + schema init
    auth/
      __init__.py
      security.py            # password hashing, TOTP
      models.py               # users/sessions/pending_logins/login_attempts DB access
      dependencies.py         # get_current_user, require_csrf
      routes.py               # /login, /login/verify, /logout
    files/
      __init__.py
      pathutils.py            # resolve_safe_path
      routes.py               # /api/files, /api/download, /api/upload, /api/rename, /api/move, DELETE /api/files
    preview/
      __init__.py
      convert.py               # docx->pdf via LibreOffice, disk cache
      routes.py                 # /view/{path}
    static/
      login.html
      login.js
      index.html
      app.js
      app.css
      viewer.html               # text/code/markdown viewer (pdf/docx use vendored pdf.js viewer)
      viewer.js
      vendor/                    # populated at container build time (pdf.js, highlight.js, marked.js)
  scripts/
    create_user.py
  tests/
    conftest.py
    test_config.py
    test_db.py
    test_security.py
    test_pathutils.py
    test_auth_routes.py
    test_files_routes.py
    test_convert.py
    test_preview_routes.py
  requirements.txt
  requirements-dev.txt
  Containerfile
  docviewer.container            # Podman Quadlet unit
  .env.example
  README.md
```

---

### Task 1: Project scaffolding, config, and health check

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`
- Test: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (pydantic `BaseSettings`, fields: `files_root: Path`, `db_path: Path`, `cache_dir: Path`, `session_ttl_seconds: int = 604800`, `pending_login_ttl_seconds: int = 300`, `max_upload_bytes: int = 2_147_483_648`, `login_lockout_threshold: int = 5`, `login_lockout_window_seconds: int = 900`, `session_secret: str`), `app.config.get_settings() -> Settings` (`lru_cache`d).
- Produces: `app.main.app` (the FastAPI instance), `GET /healthz` route.

- [ ] **Step 1: Write requirements files**

`requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic-settings==2.6.1
python-multipart==0.0.12
argon2-cffi==23.1.0
pyotp==2.9.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.3
httpx==0.27.2
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import os
from pathlib import Path

def test_settings_load_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret-value")

    from app.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.files_root == Path(tmp_path / "files")
    assert settings.db_path == Path(tmp_path / "db.sqlite3")
    assert settings.cache_dir == Path(tmp_path / "cache")
    assert settings.session_secret == "test-secret-value"
    assert settings.session_ttl_seconds == 604800
```

```python
# tests/conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or similar.

- [ ] **Step 4: Write `app/__init__.py` (empty) and `app/config.py`**

```python
# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    files_root: Path
    db_path: Path
    cache_dir: Path
    session_secret: str
    session_ttl_seconds: int = 604800
    pending_login_ttl_seconds: int = 300
    max_upload_bytes: int = 2_147_483_648
    login_lockout_threshold: int = 5
    login_lockout_window_seconds: int = 900

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Write `app/main.py` with a health check route**

```python
# app/main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

app = FastAPI(title="docviewer")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
```

- [ ] **Step 7: Write and run a smoke test for the health check**

```python
# add to tests/test_config.py
def test_healthz(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret-value")

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

---

### Task 2: SQLite schema and connection management

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.db.init_db(db_path: Path) -> None`, `app.db.get_conn() -> sqlite3.Connection` (module-level singleton, `row_factory=sqlite3.Row`), `app.db.reset_conn_for_tests() -> None` (test-only helper to force a fresh connection when `db_path` changes between tests).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
def test_init_db_creates_tables(tmp_path):
    from app import db
    db.reset_conn_for_tests()

    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    conn = db.get_conn()

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"users", "sessions", "pending_logins", "login_attempts"} <= tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write `app/db.py`**

```python
# app/db.py
import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    totp_secret TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    csrf_token TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_logins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    attempts INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ip TEXT NOT NULL,
    success INTEGER NOT NULL,
    attempted_at TEXT NOT NULL
);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    with _lock:
        conn.executescript(_SCHEMA)
        conn.commit()


def _connect(db_path: Path) -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("init_db() must be called before get_conn()")
    return _conn


def reset_conn_for_tests() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS

---

### Task 3: Password hashing and TOTP utilities

**Files:**
- Create: `app/auth/__init__.py`
- Create: `app/auth/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Produces: `app.auth.security.hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`, `generate_totp_secret() -> str`, `verify_totp(secret: str, code: str) -> bool`, `provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security.py
import pyotp


def test_password_hash_roundtrip():
    from app.auth.security import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_totp_roundtrip():
    from app.auth.security import generate_totp_secret, verify_totp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False


def test_provisioning_uri_contains_issuer_and_username():
    from app.auth.security import generate_totp_secret, provisioning_uri

    secret = generate_totp_secret()
    uri = provisioning_uri(secret, "vyshak")
    assert "docviewer" in uri
    assert "vyshak" in uri
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Write `app/auth/security.py`**

```python
# app/auth/security.py
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_security.py -v`
Expected: PASS (3 tests)

---

### Task 4: Auth data access layer (users, sessions, pending logins, lockout)

**Files:**
- Create: `app/auth/models.py`
- Test: `tests/test_auth_models.py`

**Interfaces:**
- Consumes: `app.db.get_conn()`, `app.auth.security.hash_password/verify_password`.
- Produces:
  - `create_user(username: str, password: str, totp_secret: str) -> int` (returns user id)
  - `get_user_by_username(username: str) -> sqlite3.Row | None`
  - `get_user_by_id(user_id: int) -> sqlite3.Row | None`
  - `record_login_attempt(username: str, ip: str, success: bool) -> None`
  - `is_locked_out(username: str, ip: str, threshold: int, window_seconds: int) -> bool`
  - `create_pending_login(user_id: int, ttl_seconds: int) -> str` (raw token)
  - `consume_pending_login(raw_token: str, max_attempts: int = 5) -> int | None` — returns `user_id` on success; on wrong-but-not-expired token this doesn't apply (see verify function below)
  - `verify_and_bump_pending_login(raw_token: str, max_attempts: int) -> sqlite3.Row | None` — fetches the pending row if not expired/over-attempts, else `None`
  - `delete_pending_login(raw_token: str) -> None`
  - `increment_pending_login_attempts(raw_token: str) -> None`
  - `create_session(user_id: int, ttl_seconds: int) -> tuple[str, str]` — returns `(raw_token, csrf_token)`
  - `get_session(raw_token: str) -> sqlite3.Row | None`
  - `delete_session(raw_token: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_models.py
import time
from datetime import datetime, timedelta, timezone


def _fresh_db(tmp_path):
    from app import db
    db.reset_conn_for_tests()
    db.init_db(tmp_path / "test.sqlite3")


def test_create_and_get_user(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "hunter2-but-better", "SECRET123")
    row = models.get_user_by_username("vyshak")
    assert row is not None
    assert row["id"] == user_id
    assert row["username"] == "vyshak"
    assert row["password_hash"] != "hunter2-but-better"


def test_login_attempt_lockout(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    models.create_user("vyshak", "pw", "SECRET")
    for _ in range(5):
        models.record_login_attempt("vyshak", "1.2.3.4", success=False)

    assert models.is_locked_out("vyshak", "1.2.3.4", threshold=5, window_seconds=900) is True
    assert models.is_locked_out("vyshak", "9.9.9.9", threshold=5, window_seconds=900) is False


def test_pending_login_roundtrip(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=300)

    row = models.verify_and_bump_pending_login(token, max_attempts=5)
    assert row is not None
    assert row["user_id"] == user_id

    models.delete_pending_login(token)
    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_pending_login_expires(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=-1)  # already expired

    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_pending_login_max_attempts(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=300)

    for _ in range(5):
        models.increment_pending_login_attempts(token)

    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_session_roundtrip(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, csrf = models.create_session(user_id, ttl_seconds=3600)

    row = models.get_session(raw_token)
    assert row is not None
    assert row["user_id"] == user_id
    assert row["csrf_token"] == csrf

    models.delete_session(raw_token)
    assert models.get_session(raw_token) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.models'`

- [ ] **Step 3: Write `app/auth/models.py`**

```python
# app/auth/models.py
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.auth.security import hash_password
from app.db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_user(username: str, password: str, totp_secret: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, totp_secret, created_at) VALUES (?, ?, ?, ?)",
        (username, hash_password(password), totp_secret, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_username(username: str) -> sqlite3.Row | None:
    conn = get_conn()
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    conn = get_conn()
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def record_login_attempt(username: str, ip: str, success: bool) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
        (username, ip, int(success), _now()),
    )
    conn.commit()


def is_locked_out(username: str, ip: str, threshold: int, window_seconds: int) -> bool:
    conn = get_conn()
    cutoff = _future(-window_seconds)
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM login_attempts
        WHERE username = ? AND ip = ? AND success = 0 AND attempted_at >= ?
        """,
        (username, ip, cutoff),
    ).fetchone()
    return row["n"] >= threshold


def create_pending_login(user_id: int, ttl_seconds: int) -> str:
    conn = get_conn()
    raw_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO pending_logins (token_hash, user_id, attempts, expires_at) VALUES (?, ?, 0, ?)",
        (_hash_token(raw_token), user_id, _future(ttl_seconds)),
    )
    conn.commit()
    return raw_token


def verify_and_bump_pending_login(raw_token: str, max_attempts: int) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pending_logins WHERE token_hash = ?", (_hash_token(raw_token),)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now() or row["attempts"] >= max_attempts:
        return None
    return row


def increment_pending_login_attempts(raw_token: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE pending_logins SET attempts = attempts + 1 WHERE token_hash = ?",
        (_hash_token(raw_token),),
    )
    conn.commit()


def delete_pending_login(raw_token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM pending_logins WHERE token_hash = ?", (_hash_token(raw_token),))
    conn.commit()


def create_session(user_id: int, ttl_seconds: int) -> tuple[str, str]:
    conn = get_conn()
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, csrf_token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (_hash_token(raw_token), csrf_token, user_id, _now(), _future(ttl_seconds)),
    )
    conn.commit()
    return raw_token, csrf_token


def get_session(raw_token: str) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?", (_hash_token(raw_token),)
    ).fetchone()
    if row is None or row["expires_at"] < _now():
        return None
    return row


def delete_session(raw_token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(raw_token),))
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth_models.py -v`
Expected: PASS (6 tests)

---

### Task 5: User provisioning CLI script

**Files:**
- Create: `scripts/create_user.py`

**Interfaces:**
- Consumes: `app.db.init_db`, `app.auth.models.create_user`, `app.auth.models.get_user_by_username`, `app.auth.security.generate_totp_secret`, `app.auth.security.provisioning_uri`, `app.config.get_settings`.
- Produces: a runnable CLI, no importable interface consumed by later tasks.

- [ ] **Step 1: Write the script**

```python
# scripts/create_user.py
"""Provision the single docviewer user. Run once, interactively, on the server.

Usage: python -m scripts.create_user
"""
import getpass
import sys

from app.auth import models
from app.auth.security import generate_totp_secret, provisioning_uri
from app.config import get_settings
from app.db import init_db


def main() -> None:
    settings = get_settings()
    init_db(settings.db_path)

    username = input("Username: ").strip()
    if models.get_user_by_username(username) is not None:
        print(f"User '{username}' already exists.", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(1)

    secret = generate_totp_secret()
    models.create_user(username, password, secret)

    uri = provisioning_uri(secret, username)
    print("\nUser created.")
    print("Add this account to your authenticator app.")
    print(f"\nTOTP secret (manual entry): {secret}")
    print(f"Provisioning URI (or generate a QR code from it): {uri}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manually verify**

Run (with env vars set, e.g. from `.env`): `python -m scripts.create_user`

Expected: prompts for username/password, prints a TOTP secret and `otpauth://` URI. Confirm with:

```bash
python -c "
from app.config import get_settings
from app.db import init_db, get_conn
from app.auth import models
init_db(get_settings().db_path)
print(models.get_user_by_username('<the username you entered>'))
"
```
Expected: a row is printed with the username and a non-plaintext `password_hash`.

---

### Task 6: Auth dependencies (session check, CSRF check)

**Files:**
- Create: `app/auth/dependencies.py`
- Test: `tests/test_auth_dependencies.py`

**Interfaces:**
- Consumes: `app.auth.models.get_session`, `app.auth.models.get_user_by_id`, `app.config.get_settings`.
- Produces: `get_current_user(request: Request) -> sqlite3.Row` (FastAPI dependency; raises `HTTPException(401)`), `require_csrf(request: Request, user: sqlite3.Row = Depends(get_current_user)) -> None` (raises `HTTPException(403)` on mismatch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_dependencies.py
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _fresh_db(tmp_path):
    from app import db
    db.reset_conn_for_tests()
    db.init_db(tmp_path / "test.sqlite3")


def test_get_current_user_rejects_missing_cookie(tmp_path):
    _fresh_db(tmp_path)
    from app.auth.dependencies import get_current_user

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user=Depends(get_current_user)):
        return {"username": user["username"]}

    client = TestClient(app)
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_get_current_user_accepts_valid_session(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models
    from app.auth.dependencies import get_current_user

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, _csrf = models.create_session(user_id, ttl_seconds=3600)

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user=Depends(get_current_user)):
        return {"username": user["username"]}

    client = TestClient(app)
    client.cookies.set("session_token", raw_token)
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.json() == {"username": "vyshak"}


def test_require_csrf_rejects_missing_header(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models
    from app.auth.dependencies import require_csrf

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, csrf_token = models.create_session(user_id, ttl_seconds=3600)

    app = FastAPI()

    @app.post("/mutate")
    def mutate(_=Depends(require_csrf)):
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("session_token", raw_token)
    resp = client.post("/mutate")
    assert resp.status_code == 403

    resp = client.post("/mutate", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_dependencies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.dependencies'`

- [ ] **Step 3: Write `app/auth/dependencies.py`**

```python
# app/auth/dependencies.py
import sqlite3

from fastapi import Depends, HTTPException, Request

from app.auth import models


def get_current_user(request: Request) -> sqlite3.Row:
    raw_token = request.cookies.get("session_token")
    if raw_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = models.get_session(raw_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    user = models.get_user_by_id(session["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    request.state.session = session
    return user


def require_csrf(request: Request, user: sqlite3.Row = Depends(get_current_user)) -> None:
    session = request.state.session
    header_token = request.headers.get("X-CSRF-Token")
    if not header_token or header_token != session["csrf_token"]:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth_dependencies.py -v`
Expected: PASS (3 tests)

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

---

### Task 8: Safe path resolution

**Files:**
- Create: `app/files/__init__.py`
- Create: `app/files/pathutils.py`
- Test: `tests/test_pathutils.py`

**Interfaces:**
- Produces: `app.files.pathutils.UnsafePathError(Exception)`, `resolve_safe_path(root: Path, relative: str) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pathutils.py
import pytest


def test_resolves_normal_path(tmp_path):
    from app.files.pathutils import resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()
    (root / "sub").mkdir()

    result = resolve_safe_path(root, "sub/doc.pdf")
    assert result == (root / "sub" / "doc.pdf").resolve()


def test_rejects_parent_traversal(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "../../etc/passwd")


def test_rejects_absolute_path_escape(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "/etc/passwd")


def test_rejects_symlink_escape(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "link").symlink_to(outside / "secret.txt")

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "link")


def test_empty_relative_path_returns_root(tmp_path):
    from app.files.pathutils import resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    assert resolve_safe_path(root, "") == root.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pathutils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.files'`

- [ ] **Step 3: Write `app/files/pathutils.py`**

```python
# app/files/pathutils.py
import os
from pathlib import Path


class UnsafePathError(Exception):
    pass


def resolve_safe_path(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative.lstrip("/")).resolve()

    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise UnsafePathError(f"Path escapes root: {relative}")

    return candidate
```

Note: `Path.resolve()` follows symlinks, so a symlink inside `root` that points outside it resolves to its real (outside) target before the `relative_to` check runs — that's what makes `test_rejects_symlink_escape` pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pathutils.py -v`
Expected: PASS (5 tests)

---

### Task 9: File listing and download

**Files:**
- Create: `app/files/routes.py`
- Modify: `app/main.py` (mount files router)
- Test: `tests/test_files_routes.py`

**Interfaces:**
- Consumes: `app.files.pathutils.resolve_safe_path`, `app.auth.dependencies.get_current_user`, `app.config.get_settings`.
- Produces: `app.files.routes.router`, routes `GET /api/files`, `GET /api/download/{path:path}`. (Later tasks add upload/rename/move/delete to this same router.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_routes.py
import pyotp
from fastapi.testclient import TestClient


def _authed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    settings = get_settings()
    settings.files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.db_path)

    from app.auth import models
    from app.auth.security import generate_totp_secret

    secret = generate_totp_secret()
    models.create_user("vyshak", "correct horse battery staple", secret)

    from app.main import app
    client = TestClient(app)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    return client, settings


def test_list_root_directory(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    (settings.files_root / "notes").mkdir()

    resp = client.get("/api/files", params={"path": ""})
    assert resp.status_code == 200
    names = {entry["name"] for entry in resp.json()["entries"]}
    assert names == {"report.pdf", "notes"}


def test_list_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    get_settings().files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(get_settings().db_path)

    from app.main import app
    resp = TestClient(app).get("/api/files", params={"path": ""})
    assert resp.status_code == 401


def test_list_rejects_traversal(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)
    resp = client.get("/api/files", params={"path": "../../etc"})
    assert resp.status_code == 400


def test_download_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "hello.txt").write_text("hello world")

    resp = client.get("/api/download/hello.txt")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.files.routes'`

- [ ] **Step 3: Write `app/files/routes.py`**

```python
# app/files/routes.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path

router = APIRouter(prefix="/api")


@router.get("/files")
def list_files(path: str = "", user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    for child in target.iterdir():
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return {"entries": entries}


@router.get("/download/{path:path}")
def download_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(target, filename=target.name)
```

- [ ] **Step 4: Mount the router in `app/main.py`**

```python
# add near other router imports in app/main.py
from app.files.routes import router as files_router

# add after app.include_router(auth_router)
app.include_router(files_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v`
Expected: PASS (4 tests)

---

### Task 10: File upload

**Files:**
- Modify: `app/files/routes.py` (add upload route)
- Modify: `tests/test_files_routes.py` (add upload tests)

**Interfaces:**
- Consumes: `app.auth.dependencies.require_csrf`, `app.files.pathutils.resolve_safe_path`.
- Produces: `POST /api/upload?path=` on the existing `files_router`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_files_routes.py
def test_upload_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("new.txt", b"uploaded content", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert (settings.files_root / "new.txt").read_bytes() == b"uploaded content"


def test_upload_requires_csrf(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("new.txt", b"content", "text/plain")},
    )
    assert resp.status_code == 403


def test_upload_rejects_traversal(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": "../../etc"},
        files={"file": ("evil.txt", b"content", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400


def test_upload_rejects_oversize(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    from app.config import get_settings
    get_settings().max_upload_bytes = 10  # patched via cached settings instance

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("big.txt", b"x" * 100, "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v -k upload`
Expected: FAIL — `404 Not Found` for `/api/upload` (route doesn't exist yet).

- [ ] **Step 3: Add the upload route to `app/files/routes.py`**

```python
# add imports at top of app/files/routes.py
import os

from fastapi import Query, UploadFile
from app.auth.dependencies import require_csrf

# add after download_file()
@router.post("/upload")
async def upload_file(
    file: UploadFile,
    path: str = Query(""),
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()
    try:
        target_dir = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    dest = target_dir / file.filename
    tmp_dest = target_dir / f".{file.filename}.part"

    total = 0
    with open(tmp_dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                out.close()
                tmp_dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            out.write(chunk)

    os.replace(tmp_dest, dest)
    return {"ok": True, "name": file.filename, "size": total}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v -k upload`
Expected: PASS (4 tests)

---

### Task 11: Rename, move, delete

**Files:**
- Modify: `app/files/routes.py` (add rename/move/delete routes)
- Modify: `tests/test_files_routes.py` (add tests)

**Interfaces:**
- Produces: `POST /api/rename`, `POST /api/move`, `DELETE /api/files/{path:path}` on `files_router`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_files_routes.py
def test_rename_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "new.txt"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "old.txt").exists()
    assert (settings.files_root / "new.txt").read_text() == "data"


def test_move_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "a.txt").write_text("data")
    (settings.files_root / "sub").mkdir()

    resp = client.post(
        "/api/move",
        json={"path": "a.txt", "dest": "sub/a.txt"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "a.txt").exists()
    assert (settings.files_root / "sub" / "a.txt").read_text() == "data"


def test_delete_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "gone.txt").write_text("data")

    resp = client.delete(
        "/api/files/gone.txt",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "gone.txt").exists()


def test_rename_rejects_traversal_target(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "../../etc/passwd"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v -k "rename or move or delete"`
Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Add routes to `app/files/routes.py`**

```python
# add imports
import shutil
from pydantic import BaseModel


class RenameBody(BaseModel):
    path: str
    new_name: str


class MoveBody(BaseModel):
    path: str
    dest: str


# add after upload_file()
@router.post("/rename")
def rename_file(body: RenameBody, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    if "/" in body.new_name or body.new_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid new name")

    try:
        source = resolve_safe_path(settings.files_root, body.path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # new_name has no "/" (checked above), so it's a single path segment —
    # source.parent / new_name necessarily stays within source's own directory.
    target = source.parent / body.new_name

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    source.rename(target)
    return {"ok": True}


@router.post("/move")
def move_file(body: MoveBody, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    try:
        source = resolve_safe_path(settings.files_root, body.path)
        dest = resolve_safe_path(settings.files_root, body.dest)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if dest.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return {"ok": True}


@router.delete("/files/{path:path}")
def delete_file(path: str, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v`
Expected: PASS (all tests in the file)

---

### Task 12: Docx/doc to PDF conversion with disk cache

**Files:**
- Create: `app/preview/__init__.py`
- Create: `app/preview/convert.py`
- Test: `tests/test_convert.py`

**Interfaces:**
- Produces: `app.preview.convert.ConversionError(Exception)`, `get_preview_pdf(source: Path, cache_dir: Path, timeout: int = 120) -> Path`.
- This task mocks `subprocess.run` in tests — it does not require LibreOffice to be installed on the dev machine to pass.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_convert.py
from pathlib import Path
from unittest.mock import patch


def test_returns_cached_pdf_without_reconverting(tmp_path):
    from app.preview.convert import get_preview_pdf

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from app.preview.convert import _cache_key
    key = _cache_key(source)
    cached_pdf = cache_dir / f"{key}.pdf"
    cached_pdf.write_bytes(b"%PDF-1.4 cached")

    with patch("app.preview.convert.subprocess.run") as mock_run:
        result = get_preview_pdf(source, cache_dir)
        mock_run.assert_not_called()

    assert result == cached_pdf


def test_converts_when_not_cached(tmp_path):
    from app.preview.convert import get_preview_pdf, _cache_key

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    key = _cache_key(source)
    expected_output = cache_dir / f"{key}.pdf"

    def fake_run(cmd, timeout, capture_output, check):
        # Real LibreOffice names output after the source stem, not our cache
        # key — get_preview_pdf must rename it into place after conversion.
        (cache_dir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.4 converted")

        class Result:
            returncode = 0

        return Result()

    with patch("app.preview.convert.subprocess.run", side_effect=fake_run) as mock_run:
        result = get_preview_pdf(source, cache_dir)
        mock_run.assert_called_once()

    assert result == expected_output
    assert result.read_bytes() == b"%PDF-1.4 converted"


def test_raises_on_conversion_failure(tmp_path):
    from app.preview.convert import ConversionError, get_preview_pdf

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class Result:
        returncode = 1

    with patch("app.preview.convert.subprocess.run", return_value=Result()):
        try:
            get_preview_pdf(source, cache_dir)
            assert False, "expected ConversionError"
        except ConversionError:
            pass


def test_cache_key_changes_with_mtime(tmp_path):
    from app.preview.convert import _cache_key
    import os

    source = tmp_path / "doc.docx"
    source.write_bytes(b"v1")
    key1 = _cache_key(source)

    os.utime(source, (source.stat().st_atime, source.stat().st_mtime + 10))
    key2 = _cache_key(source)

    assert key1 != key2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_convert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.preview'`

- [ ] **Step 3: Write `app/preview/convert.py`**

LibreOffice's `--convert-to` names its output after the *source* filename
(`<source_stem>.pdf`), not our cache key — so the function converts into a
temp name and renames to the cache-key filename afterward.

```python
# app/preview/convert.py
import hashlib
import subprocess
from pathlib import Path


class ConversionError(Exception):
    pass


def _cache_key(source: Path) -> str:
    mtime_ns = source.stat().st_mtime_ns
    raw = f"{source.resolve()}:{mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_preview_pdf(source: Path, cache_dir: Path, timeout: int = 120) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(source)
    cached = cache_dir / f"{key}.pdf"

    if cached.exists():
        return cached

    result = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(cache_dir),
            str(source),
        ],
        timeout=timeout,
        capture_output=True,
        check=False,
    )

    produced = cache_dir / f"{source.stem}.pdf"

    if result.returncode != 0 or not produced.exists():
        raise ConversionError(f"Failed to convert {source} to PDF")

    if produced != cached:
        produced.replace(cached)

    return cached
```

Note the test's `fake_run` above writes to `cache_dir / f"{source.stem}.pdf"`
(not directly to the cache-key path) precisely to exercise this rename step —
that's the real LibreOffice output-naming behavior being simulated.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_convert.py -v`
Expected: PASS (4 tests)

---

### Task 13: Preview route (`/view/{path}`)

**Files:**
- Create: `app/preview/routes.py`
- Modify: `app/main.py` (mount preview router)
- Test: `tests/test_preview_routes.py`

**Interfaces:**
- Consumes: `app.preview.convert.get_preview_pdf`, `app.files.pathutils.resolve_safe_path`, `app.auth.dependencies.get_current_user`.
- Produces: `app.preview.routes.router`, route `GET /view/{path:path}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preview_routes.py
from unittest.mock import patch
import pyotp
from fastapi.testclient import TestClient


def _authed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    settings = get_settings()
    settings.files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.db_path)

    from app.auth import models
    from app.auth.security import generate_totp_secret

    secret = generate_totp_secret()
    models.create_user("vyshak", "correct horse battery staple", secret)

    from app.main import app
    client = TestClient(app)
    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    return client, settings


def test_view_pdf_streams_directly(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "doc.pdf").write_bytes(b"%PDF-1.4 raw")

    resp = client.get("/view/doc.pdf")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 raw"
    assert resp.headers["content-type"] == "application/pdf"


def test_view_docx_converts_via_cache(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "doc.docx").write_bytes(b"fake docx")

    with patch("app.preview.routes.get_preview_pdf") as mock_convert:
        mock_convert.return_value = None

        def side_effect(source, cache_dir):
            out = cache_dir / "doc.pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"%PDF-1.4 converted")
            return out

        mock_convert.side_effect = side_effect

        resp = client.get("/view/doc.docx")

    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 converted"


def test_view_unsupported_type_returns_415(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "image.png").write_bytes(b"fake png")

    resp = client.get("/view/image.png")
    assert resp.status_code == 415


def test_view_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    get_settings().files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(get_settings().db_path)

    from app.main import app
    resp = TestClient(app).get("/view/doc.pdf")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_preview_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.preview.routes'`

- [ ] **Step 3: Write `app/preview/routes.py`**

```python
# app/preview/routes.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path
from app.preview.convert import ConversionError, get_preview_pdf

router = APIRouter()

_DOC_EXTENSIONS = {".docx", ".doc"}


@router.get("/view/{path:path}")
def view_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = target.suffix.lower()

    if suffix == ".pdf":
        return FileResponse(target, media_type="application/pdf")

    if suffix in _DOC_EXTENSIONS:
        try:
            pdf_path = get_preview_pdf(target, settings.cache_dir)
        except ConversionError:
            raise HTTPException(status_code=502, detail="Conversion failed")
        return FileResponse(pdf_path, media_type="application/pdf")

    raise HTTPException(status_code=415, detail="Unsupported preview type")
```

- [ ] **Step 4: Mount the router in `app/main.py`**

```python
# add near other router imports
from app.preview.routes import router as preview_router

# add after app.include_router(files_router)
app.include_router(preview_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_preview_routes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: All tests across all files PASS.

---

### Task 14: Frontend — login page

**Files:**
- Create: `app/static/login.html`
- Create: `app/static/login.js`
- Modify: `app/main.py` (mount `/static`, serve login page at `/`)

**Interfaces:**
- Consumes: `POST /login`, `POST /login/verify` (Task 7).
- Produces: a working login UI at `/`.

- [ ] **Step 1: Write `app/static/login.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer — sign in</title>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body class="auth-page">
  <main class="auth-card">
    <h1>docviewer</h1>

    <form id="password-form">
      <label>Username <input type="text" name="username" autocomplete="username" required /></label>
      <label>Password <input type="password" name="password" autocomplete="current-password" required /></label>
      <button type="submit">Continue</button>
      <p class="error" id="password-error"></p>
    </form>

    <form id="totp-form" hidden>
      <label>Authenticator code <input type="text" name="code" inputmode="numeric" autocomplete="one-time-code" required /></label>
      <button type="submit">Sign in</button>
      <p class="error" id="totp-error"></p>
    </form>
  </main>
  <script src="/static/login.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app/static/login.js`**

```javascript
const passwordForm = document.getElementById("password-form");
const totpForm = document.getElementById("totp-form");
const passwordError = document.getElementById("password-error");
const totpError = document.getElementById("totp-error");

passwordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  passwordError.textContent = "";
  const formData = new FormData(passwordForm);

  const resp = await fetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: formData.get("username"),
      password: formData.get("password"),
    }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    passwordError.textContent = body.detail || "Login failed";
    return;
  }

  passwordForm.hidden = true;
  totpForm.hidden = false;
});

totpForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  totpError.textContent = "";
  const formData = new FormData(totpForm);

  const resp = await fetch("/login/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: formData.get("code") }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    totpError.textContent = body.detail || "Invalid code";
    return;
  }

  window.location.href = "/app";
});
```

- [ ] **Step 3: Wire up static file serving in `app/main.py`**

```python
# add imports at top
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# add after app.include_router(preview_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def login_page():
    return FileResponse("app/static/login.html")
```

- [ ] **Step 4: Manual verification**

Run the app locally: `uvicorn app.main:app --reload` (with `.env` pointing at a scratch `FILES_ROOT`/`DB_PATH`/`CACHE_DIR`, and a user already created via Task 5's script).

In a browser, open `http://127.0.0.1:8000/`, submit the password form, then the TOTP form with a code from an authenticator app (or `pyotp.TOTP(secret).now()` in a REPL). Confirm it redirects to `/app` (which will 404 until Task 15 — that 404 is expected here) and that the `session_token` cookie is set (check browser devtools).

---

### Task 15: Frontend — file browser page

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/app.js`
- Create: `app/static/app.css`
- Modify: `app/main.py` (serve `/app`, protect it)

**Interfaces:**
- Consumes: `GET /api/files`, `POST /api/upload`, `POST /api/rename`, `POST /api/move`, `DELETE /api/files/{path}` (Tasks 9-11).
- Produces: a working file browser UI at `/app`.

- [ ] **Step 1: Write `app/static/app.css`**

```css
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
.auth-page { display: flex; align-items: center; justify-content: center; height: 100vh; }
.auth-card { background: #1a1d24; padding: 2rem; border-radius: 8px; width: 320px; }
.auth-card label { display: block; margin-bottom: 1rem; }
.auth-card input { width: 100%; padding: 0.5rem; margin-top: 0.25rem; }
.error { color: #ff6b6b; min-height: 1.2em; }
header { display: flex; align-items: center; gap: 1rem; padding: 1rem; border-bottom: 1px solid #2a2d36; }
#breadcrumbs a { color: #8ab4f8; text-decoration: none; margin-right: 0.25rem; }
table { width: 100%; border-collapse: collapse; margin: 1rem; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #2a2d36; }
tr.entry:hover { background: #1a1d24; cursor: pointer; }
.actions button { margin-right: 0.5rem; }
```

- [ ] **Step 2: Write `app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer</title>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body>
  <header>
    <strong>docviewer</strong>
    <nav id="breadcrumbs"></nav>
    <span style="flex: 1"></span>
    <input type="file" id="upload-input" hidden />
    <button id="upload-button">Upload</button>
    <button id="logout-button">Log out</button>
  </header>
  <table>
    <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead>
    <tbody id="entries"></tbody>
  </table>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `app/static/app.js`**

```javascript
function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function csrfHeaders() {
  return { "X-CSRF-Token": getCookie("csrf_token") };
}

let currentPath = "";

const PREVIEWABLE = new Set([".pdf", ".docx", ".doc"]);
const TEXT_LIKE = new Set([".txt", ".md", ".py", ".js", ".json", ".c", ".h", ".css", ".html", ".sh", ".yaml", ".yml"]);

function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

async function loadEntries(path) {
  const resp = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
  if (resp.status === 401) {
    window.location.href = "/";
    return;
  }
  const data = await resp.json();
  currentPath = path;
  renderBreadcrumbs(path);
  renderEntries(data.entries, path);
}

function renderBreadcrumbs(path) {
  const el = document.getElementById("breadcrumbs");
  el.innerHTML = "";
  const rootLink = document.createElement("a");
  rootLink.textContent = "root";
  rootLink.href = "#";
  rootLink.onclick = () => loadEntries("");
  el.appendChild(rootLink);

  if (!path) return;
  const parts = path.split("/").filter(Boolean);
  let acc = "";
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part;
    el.appendChild(document.createTextNode(" / "));
    const link = document.createElement("a");
    link.textContent = part;
    const target = acc;
    link.onclick = () => loadEntries(target);
    el.appendChild(link);
  }
}

function renderEntries(entries, path) {
  const tbody = document.getElementById("entries");
  tbody.innerHTML = "";
  entries.sort((a, b) => (b.is_dir - a.is_dir) || a.name.localeCompare(b.name));

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.className = "entry";

    const nameCell = document.createElement("td");
    nameCell.textContent = entry.is_dir ? `📁 ${entry.name}` : entry.name;
    nameCell.onclick = () => openEntry(entry, path);
    row.appendChild(nameCell);

    const sizeCell = document.createElement("td");
    sizeCell.textContent = entry.is_dir ? "" : `${entry.size} B`;
    row.appendChild(sizeCell);

    const mtimeCell = document.createElement("td");
    mtimeCell.textContent = new Date(entry.mtime * 1000).toLocaleString();
    row.appendChild(mtimeCell);

    const actionsCell = document.createElement("td");
    actionsCell.className = "actions";
    actionsCell.appendChild(makeButton("Rename", () => renameEntry(entry, path)));
    actionsCell.appendChild(makeButton("Delete", () => deleteEntry(entry, path)));
    row.appendChild(actionsCell);

    tbody.appendChild(row);
  }
}

function makeButton(label, onClick) {
  const button = document.createElement("button");
  button.textContent = label;
  button.onclick = (event) => {
    event.stopPropagation();
    onClick();
  };
  return button;
}

function openEntry(entry, path) {
  const fullPath = path ? `${path}/${entry.name}` : entry.name;
  if (entry.is_dir) {
    loadEntries(fullPath);
    return;
  }
  const ext = extensionOf(entry.name);
  if (PREVIEWABLE.has(ext)) {
    window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent("/view/" + fullPath)}`, "_blank");
  } else if (TEXT_LIKE.has(ext)) {
    window.open(`/static/viewer.html?path=${encodeURIComponent(fullPath)}`, "_blank");
  } else {
    window.open(`/api/download/${fullPath}`, "_blank");
  }
}

async function renameEntry(entry, path) {
  const newName = prompt("New name", entry.name);
  if (!newName || newName === entry.name) return;
  const fullPath = path ? `${path}/${entry.name}` : entry.name;

  const resp = await fetch("/api/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...csrfHeaders() },
    body: JSON.stringify({ path: fullPath, new_name: newName }),
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Rename failed");
}

async function deleteEntry(entry, path) {
  if (!confirm(`Delete ${entry.name}?`)) return;
  const fullPath = path ? `${path}/${entry.name}` : entry.name;

  const resp = await fetch(`/api/files/${fullPath}`, {
    method: "DELETE",
    headers: csrfHeaders(),
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Delete failed");
}

document.getElementById("upload-button").onclick = () => {
  document.getElementById("upload-input").click();
};

document.getElementById("upload-input").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);

  const resp = await fetch(`/api/upload?path=${encodeURIComponent(currentPath)}`, {
    method: "POST",
    headers: csrfHeaders(),
    body: formData,
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Upload failed");
};

document.getElementById("logout-button").onclick = async () => {
  await fetch("/logout", { method: "POST", headers: csrfHeaders() });
  window.location.href = "/";
};

loadEntries("");
```

- [ ] **Step 4: Serve `/app` in `app/main.py`, gated on a valid session**

```python
# add after the "/" route in app/main.py
from fastapi import Depends
from app.auth.dependencies import get_current_user


@app.get("/app")
def app_page(user=Depends(get_current_user)):
    return FileResponse("app/static/index.html")
```

- [ ] **Step 5: Manual verification**

With the server running and a user logged in (Task 14), navigate to `/app`. Confirm: directory listing renders, breadcrumbs update on folder click, upload adds a file to the list, rename/delete work and refresh the list. Note: clicking a PDF/docx will 404 on the vendored viewer path until Task 17 builds the container image — that's expected at this point; verify the `/view/{path}` request itself succeeds by checking the Network tab.

---

### Task 16: Frontend — text/code/markdown viewer

**Files:**
- Create: `app/static/viewer.html`
- Create: `app/static/viewer.js`

**Interfaces:**
- Consumes: `GET /api/download/{path}` (Task 9), vendored `highlight.js` and `marked.js` (populated by Task 17's Containerfile) at `/static/vendor/highlight/` and `/static/vendor/marked/`.

- [ ] **Step 1: Write `app/static/viewer.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer — preview</title>
  <link rel="stylesheet" href="/static/app.css" />
  <link rel="stylesheet" href="/static/vendor/highlight/styles/github-dark.min.css" />
  <style>
    #content { margin: 1rem; }
    pre { white-space: pre-wrap; word-break: break-word; }
  </style>
</head>
<body>
  <div id="content">Loading…</div>
  <script src="/static/vendor/marked/marked.min.js"></script>
  <script src="/static/vendor/highlight/highlight.min.js"></script>
  <script src="/static/viewer.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app/static/viewer.js`**

```javascript
function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

async function render() {
  const params = new URLSearchParams(window.location.search);
  const path = params.get("path");
  const content = document.getElementById("content");

  if (!path) {
    content.textContent = "No file specified.";
    return;
  }

  const resp = await fetch(`/api/download/${path}`);
  if (!resp.ok) {
    content.textContent = `Failed to load file (${resp.status})`;
    return;
  }
  const text = await resp.text();
  const ext = extensionOf(path);

  if (ext === ".md") {
    content.innerHTML = marked.parse(text);
  } else {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = text;
    pre.appendChild(code);
    content.innerHTML = "";
    content.appendChild(pre);
    if (window.hljs) hljs.highlightElement(code);
  }
}

render();
```

- [ ] **Step 3: Manual verification**

Deferred to Task 17/18 manual verification, once `highlight.js`/`marked.js` are vendored by the container build — this task has no automated test since it's pure frontend code with no server logic to unit test.

---

### Task 17: Containerfile (vendors frontend assets, installs LibreOffice, runs the app)

**Files:**
- Create: `Containerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt`, the full `app/` tree.
- Produces: a buildable OCI image that serves the app on port 8000 as a non-root user.

- [ ] **Step 1: Write `.dockerignore`**

```
tests/
docs/
.env
*.sqlite3
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Write `Containerfile`**

```dockerfile
# --- stage 1: fetch frontend vendor assets ---
FROM node:20-slim AS assets
WORKDIR /assets
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip jq \
    && rm -rf /var/lib/apt/lists/*

# pdf.js prebuilt viewer (full web app, not on npm) — always grab the latest GitHub release asset
RUN curl -sL "$(curl -s https://api.github.com/repos/mozilla/pdf.js/releases/latest \
      | jq -r '.assets[] | select(.name | endswith("dist.zip")) | .browser_download_url')" \
      -o pdfjs.zip \
    && mkdir -p vendor/pdfjs \
    && unzip -q pdfjs.zip -d vendor/pdfjs

# highlight.js prebuilt CDN-style bundle from its latest GitHub release
RUN curl -sL "$(curl -s https://api.github.com/repos/highlightjs/highlight.js/releases/latest \
      | jq -r '.assets[] | select(.name | test("highlight.js-.*\\.zip")) | .browser_download_url' | head -n1)" \
      -o hljs.zip \
    && mkdir -p vendor/highlight \
    && unzip -q hljs.zip -d vendor/highlight

# marked — single-file build, via npm
RUN npm install marked \
    && mkdir -p vendor/marked \
    && cp node_modules/marked/marked.min.js vendor/marked/marked.min.js

# --- stage 2: application image ---
FROM python:3.12-slim
WORKDIR /srv/app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer \
      libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
COPY --from=assets /assets/vendor/pdfjs app/static/vendor/pdfjs
COPY --from=assets /assets/vendor/highlight app/static/vendor/highlight
COPY --from=assets /assets/vendor/marked app/static/vendor/marked

RUN mkdir -p /data/files /data/cache /data/db \
    && chown -R appuser:appuser /srv/app /data

USER appuser
EXPOSE 8000

ENV FILES_ROOT=/data/files \
    DB_PATH=/data/db/docviewer.sqlite3 \
    CACHE_DIR=/data/cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: `SESSION_SECRET` is intentionally not baked into the image — it's supplied at runtime (Task 18's Quadlet unit / `.env`), since it must be unique per deployment and never committed.

- [ ] **Step 3: Manual verification — build and smoke-test the image**

```bash
podman build -t docviewer:local -f Containerfile .
podman run --rm -p 8000:8000 \
  -e SESSION_SECRET="$(openssl rand -hex 32)" \
  -v /tmp/docviewer-files:/data/files \
  docviewer:local
```

In another terminal: `curl http://127.0.0.1:8000/healthz` — expect `{"status":"ok"}`.

Then, inside the running container, provision the one user:

```bash
podman exec -it <container-id> python -m scripts.create_user
```

Visit `http://127.0.0.1:8000/` in a browser, log in with the account just created, confirm the file browser loads, upload a `.pdf` and a `.docx`, and confirm both preview correctly through the vendored PDF.js viewer (the docx one takes a few seconds the first time — that's the LibreOffice conversion running).

---

### Task 18: Podman Quadlet unit and deployment README

**Files:**
- Create: `docviewer.container`
- Create: `.env.example`
- Create: `README.md`

**Interfaces:**
- Consumes: the image built in Task 17.
- Produces: a systemd-managed, auto-restarting deployment.

- [ ] **Step 1: Write `.env.example`**

```
SESSION_SECRET=changeme-generate-with-openssl-rand-hex-32
```

- [ ] **Step 2: Write `docviewer.container`** (Podman Quadlet unit — place at `~/.config/containers/systemd/docviewer.container` for a rootless user service, or `/etc/containers/systemd/docviewer.container` for a system-wide one)

```ini
[Unit]
Description=docviewer file browser
After=network-online.target

[Container]
Image=localhost/docviewer:local
PublishPort=127.0.0.1:8000:8000
Volume=%h/docviewer-data/files:/data/files:Z
Volume=%h/docviewer-data/state:/data/db:Z
Volume=%h/docviewer-data/state-cache:/data/cache:Z
EnvironmentFile=%h/docviewer-data/docviewer.env

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Replace `%h/docviewer-data/files` with the real path to the existing document collection before first start (this is the `FILES_ROOT` the spec calls a deploy-time decision).

- [ ] **Step 3: Write `README.md`**

```markdown
# docviewer

Lightweight, self-hosted PDF/docx/text viewer and file manager. See
`docs/superpowers/specs/2026-08-25-docviewer-design.md` for the full design.

## Deploy (Fedora Server, rootless Podman)

1. Build the image: `podman build -t docviewer:local -f Containerfile .`
2. Create data directories:
   ```bash
   mkdir -p ~/docviewer-data/state ~/docviewer-data/state-cache
   # point files at your existing document collection, e.g. a bind mount or symlink:
   ln -s /path/to/existing/documents ~/docviewer-data/files
   ```
3. Create `~/docviewer-data/docviewer.env` from `.env.example`, with a real
   `SESSION_SECRET` (`openssl rand -hex 32`).
4. Copy `docviewer.container` to `~/.config/containers/systemd/`.
5. Reload and start:
   ```bash
   systemctl --user daemon-reload
   systemctl --user start docviewer.service
   systemctl --user enable docviewer.service
   ```
6. Provision the one user account:
   ```bash
   podman exec -it systemd-docviewer python -m scripts.create_user
   ```
   Scan the printed QR/URI into an authenticator app (Aegis, Google
   Authenticator, etc).
7. Point your existing `cloudflared` tunnel at `127.0.0.1:8000` under a new
   hostname (e.g. `files.yourdomain.com`), in `~/.cloudflared/config.yml`:
   ```yaml
   ingress:
     - hostname: files.yourdomain.com
       service: http://127.0.0.1:8000
     # ...your other existing ingress rules...
   ```
   Then `systemctl restart cloudflared` (or however your existing tunnel
   service is managed).

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # edit FILES_ROOT/DB_PATH/CACHE_DIR/SESSION_SECRET for local paths
pytest
uvicorn app.main:app --reload
```

Note: local dev without the container won't have `app/static/vendor/`
populated (that's assembled by the Containerfile build) — the login page
and file browser work, but PDF/docx/markdown preview will 404 on vendored
assets until you either build the container or manually populate
`app/static/vendor/` yourself.
```

- [ ] **Step 4: Manual verification**

Follow the README's deploy steps end-to-end on the actual Fedora server against a **copy** of a small test directory first (not the real document collection), confirm the service survives `systemctl --user restart docviewer.service` and comes back up with sessions cleared but files intact, then point `FILES_ROOT` at the real collection and add the Cloudflare Tunnel hostname.

---

## Post-plan check

After Task 18, run the full suite once more and confirm coverage:

```bash
pytest -v
```

Expected: every test file passes. This exercises Tasks 1-13 (everything with server-side logic); Tasks 14-16 (frontend) and 17-18 (deployment) are verified manually per their own steps, consistent with the spec's testing section (pytest for backend logic, manual browser pass for UI/UX).
