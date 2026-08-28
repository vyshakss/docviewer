# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

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

