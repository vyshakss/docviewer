# Task 6 Report: Auth dependencies (session check, CSRF check)

## Summary

Implemented `app/auth/dependencies.py`, providing the two FastAPI dependencies
that all future protected/mutating routes will use: `get_current_user` and
`require_csrf`. Followed the brief's TDD steps exactly: wrote the test file
first, confirmed it failed with `ModuleNotFoundError`, then wrote the
implementation verbatim from the brief, and confirmed all tests pass.

## Files created/modified

- **Created** `/run/media/vyshak/ssd/docviewer/tests/test_auth_dependencies.py`
  — copied verbatim from the brief (Step 1). Three tests:
  - `test_get_current_user_rejects_missing_cookie`
  - `test_get_current_user_accepts_valid_session`
  - `test_require_csrf_rejects_missing_header`
- **Created** `/run/media/vyshak/ssd/docviewer/app/auth/dependencies.py`
  — copied verbatim from the brief (Step 3). Defines:
  - `get_current_user(request: Request) -> sqlite3.Row` — reads the
    `session_token` cookie, looks up the session via
    `app.auth.models.get_session`, resolves the user via
    `app.auth.models.get_user_by_id`, stashes the session row on
    `request.state.session` for downstream use, and raises
    `HTTPException(401)` on any failure (missing cookie, invalid/expired
    session, or missing user).
  - `require_csrf(request: Request, user=Depends(get_current_user)) -> None`
    — reads `request.state.session` (set by `get_current_user`), compares
    the `X-CSRF-Token` header against `session["csrf_token"]`, and raises
    `HTTPException(403)` on mismatch or missing header.

No other existing files were modified. No changes were needed to
`app/auth/models.py`, `app/config.py`, or `app/db.py` — their existing
interfaces (`get_session`, `get_user_by_id`, `create_session`, `create_user`,
`reset_conn_for_tests`, `init_db`) matched the brief's expectations exactly.

## Test commands and output

### Step 2: Verify test fails before implementation exists

Command:
```
.venv/bin/pytest tests/test_auth_dependencies.py -v
```

Result: **3 failed**, all with the expected error:
```
ModuleNotFoundError: No module named 'app.auth.dependencies'
```
(Full failure output confirmed for all three test functions before writing
the implementation.)

### Step 4: Verify test passes after implementation

Command:
```
.venv/bin/pytest tests/test_auth_dependencies.py -v
```

Result:
```
tests/test_auth_dependencies.py::test_get_current_user_rejects_missing_cookie PASSED [ 33%]
tests/test_auth_dependencies.py::test_get_current_user_accepts_valid_session PASSED [ 66%]
tests/test_auth_dependencies.py::test_require_csrf_rejects_missing_header PASSED [100%]

======================== 3 passed, 26 warnings in 0.68s ========================
```
(Warnings are pre-existing `DeprecationWarning`s from Starlette/FastAPI on
Python 3.14, unrelated to this change.)

### Full suite regression check

Command:
```
.venv/bin/pytest -v
```

Result: **16 passed** (13 pre-existing tests from Tasks 1-5 plus the 3 new
ones), 0 failed. No regressions introduced.

## Deviations from the brief

None. The test file and implementation file were written verbatim as
specified in the brief's Step 1 and Step 3 code blocks. Function signatures
(`get_current_user(request: Request) -> sqlite3.Row`,
`require_csrf(request: Request, user: sqlite3.Row = Depends(get_current_user)) -> None`)
match the "Produces" interface contract exactly, so downstream tasks that
depend on these exact names can rely on them as documented.
