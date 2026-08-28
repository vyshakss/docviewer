# Task 2 Report: SQLite schema and connection management

## Summary

Implemented `app/db.py` providing SQLite schema initialization and a module-level
singleton connection, following the brief exactly (`.sdd/briefs/task-2-brief.md`).
Followed the prescribed TDD steps in order: wrote the failing test, verified the
failure, wrote the implementation verbatim from the brief, verified it passes.

## Files created / modified

- **Created:** `/run/media/vyshak/ssd/docviewer/tests/test_db.py`
  Test `test_init_db_creates_tables` — copied verbatim from the brief. Calls
  `db.reset_conn_for_tests()`, then `db.init_db(tmp_path / "test.sqlite3")`,
  then asserts the four expected tables (`users`, `sessions`, `pending_logins`,
  `login_attempts`) exist in `sqlite_master`.

- **Created:** `/run/media/vyshak/ssd/docviewer/app/db.py`
  Copied verbatim from the brief. Provides:
  - `init_db(db_path: Path) -> None` — creates parent dirs, opens/creates the
    module-level connection, and runs the schema script (`CREATE TABLE IF NOT
    EXISTS` for `users`, `sessions`, `pending_logins`, `login_attempts`),
    committed under a `threading.Lock`.
  - `_connect(db_path: Path) -> sqlite3.Connection` — internal helper that
    lazily creates the singleton connection with `row_factory=sqlite3.Row`,
    `check_same_thread=False`, and `PRAGMA foreign_keys = ON`.
  - `get_conn() -> sqlite3.Connection` — returns the singleton connection;
    raises `RuntimeError` if `init_db()` hasn't been called yet.
  - `reset_conn_for_tests() -> None` — closes and clears the singleton
    connection so tests can force a fresh connection when `db_path` changes
    between tests.

- **Not modified:** `tests/conftest.py` (left untouched, as instructed — it
  already adds the project root to `sys.path`).

## Files NOT modified

No other files were touched. No git commands were run (per instructions —
this project intentionally does not use git).

## Test commands and output

### Step 2: Verify the test fails before implementation

```
$ .venv/bin/pytest tests/test_db.py -v
```

Result: **FAILED** as expected —

```
tests/test_db.py::test_init_db_creates_tables FAILED                     [100%]
...
E       ImportError: cannot import name 'db' from 'app' (/run/media/vyshak/ssd/docviewer/app/__init__.py)
tests/test_db.py:2: ImportError
=========================== short test summary info ============================
FAILED tests/test_db.py::test_init_db_creates_tables - ImportError: cannot im...
============================== 1 failed in 0.12s ===============================
```

(Note: brief predicted `ModuleNotFoundError: No module named 'app.db'`; actual
error was `ImportError: cannot import name 'db' from 'app'`, because
`app/__init__.py` already exists as a package from Task 1 — the module simply
didn't exist yet under it. Functionally equivalent: the import fails because
`app/db.py` does not exist. This is a benign deviation from the brief's
predicted error text, not from its intent.)

### Step 4: Verify the test passes after implementation

```
$ .venv/bin/pytest tests/test_db.py -v
```

Result: **PASSED**

```
tests/test_db.py::test_init_db_creates_tables PASSED                     [100%]
============================== 1 passed in 0.03s ===============================
```

### Full regression check

```
$ .venv/bin/pytest -v
```

Result: **3 passed** (`test_config.py::test_settings_load_from_env`,
`test_config.py::test_healthz`, `test_db.py::test_init_db_creates_tables`),
9 warnings (all pre-existing Pydantic/Starlette/FastAPI deprecation warnings
unrelated to this task's changes, present before this task as well).

## Deviations from the brief

None in code or test content — `app/db.py` and `tests/test_db.py` were written
verbatim as specified in the brief. The only deviation is cosmetic: the actual
exception type/message observed in Step 2 (`ImportError: cannot import name
'db' from 'app'`) differs textually from the brief's predicted
`ModuleNotFoundError: No module named 'app.db'`, due to `app/` already being
an initialized package from Task 1. This does not affect correctness — the
test still failed for the expected reason (module absent) before
implementation, and passed after.

## Interfaces produced (for downstream tasks)

- `app.db.init_db(db_path: Path) -> None`
- `app.db.get_conn() -> sqlite3.Connection` (module-level singleton,
  `row_factory=sqlite3.Row`)
- `app.db.reset_conn_for_tests() -> None` (test-only helper)

Schema tables created: `users`, `sessions`, `pending_logins`,
`login_attempts` — matching the exact column definitions in the brief,
including the `token_hash`-based session/pending-login storage (per the
global constraint that DB reads must never yield a usable session token) and
`PRAGMA foreign_keys = ON`.
