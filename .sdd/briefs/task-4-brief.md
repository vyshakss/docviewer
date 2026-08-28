# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

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

