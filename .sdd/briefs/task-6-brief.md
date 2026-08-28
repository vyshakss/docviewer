# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

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

