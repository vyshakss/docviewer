# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

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

