# Task 7 Report: Login, TOTP verify, and logout routes

## Files created
- `/run/media/vyshak/ssd/docviewer/app/auth/routes.py` — new `APIRouter` with `POST /login`, `POST /login/verify`, `POST /logout`, implemented verbatim from the brief (Step 3). Uses `app.auth.models.*`, `app.auth.security.verify_password`/`verify_totp`, `app.auth.dependencies.get_current_user`, and `app.config.get_settings`, exactly as specified in the brief's Interfaces section.
- `/run/media/vyshak/ssd/docviewer/tests/test_auth_routes.py` — new test file with the brief's 5 tests (`test_login_flow_success`, `test_login_wrong_password`, `test_login_lockout_after_repeated_failures`, `test_login_verify_wrong_code`, `test_logout_clears_session`). One deviation from the verbatim brief text — see "Deviations" below.

## Files modified
- `/run/media/vyshak/ssd/docviewer/app/main.py` — added `from app.auth.routes import router as auth_router`, `app.include_router(auth_router)`, and an `@app.on_event("startup")` handler that calls `init_db(get_settings().db_path)`. The existing security-headers middleware and `/healthz` route (from Task 1) were preserved unchanged, just placed after the new additions.

Final `app/main.py`:
```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.auth.routes import router as auth_router

app = FastAPI(title="docviewer")
app.include_router(auth_router)


@app.on_event("startup")
def _startup() -> None:
    from app.config import get_settings
    from app.db import init_db

    init_db(get_settings().db_path)


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

## Steps followed (per brief)

1. **Wrote the failing test** at `tests/test_auth_routes.py` using the brief's exact test code.
2. **Ran it to confirm failure** before any implementation existed:
   ```
   $ pytest tests/test_auth_routes.py -v
   ```
   Result: all 5 tests failed with 404s (no `/login`, `/login/verify`, `/logout` routes mounted yet) — equivalent failure mode to the brief's expected `ModuleNotFoundError` (in this repo `app/auth/routes.py` didn't exist as a file, and once the module didn't exist the import in the test setup itself would also fail; confirmed the routes were unreachable prior to implementation).
3. **Wrote `app/auth/routes.py`** verbatim from Step 3 of the brief.
4. **Mounted the router in `app/main.py`** per Step 4 of the brief, preserving existing middleware/route.
5. **Ran the test again** — see below.

## Test commands and output

First run after implementing routes.py and main.py (before the test-harness fix described in Deviations):
```
$ pytest tests/test_auth_routes.py -v
...
FAILED tests/test_auth_routes.py::test_login_flow_success - assert 401 == 200
FAILED tests/test_auth_routes.py::test_logout_clears_session - assert 401 == 200
3 passed, 2 failed
```

After applying the `base_url="https://testserver"` fix to `_setup_app` in the test file:
```
$ pytest tests/test_auth_routes.py -v
tests/test_auth_routes.py::test_login_flow_success PASSED
tests/test_auth_routes.py::test_login_wrong_password PASSED
tests/test_auth_routes.py::test_login_lockout_after_repeated_failures PASSED
tests/test_auth_routes.py::test_login_verify_wrong_code PASSED
tests/test_auth_routes.py::test_logout_clears_session PASSED
5 passed, 39 warnings in 1.49s
```

Full suite (regression check):
```
$ pytest -v
tests/test_auth_dependencies.py::test_get_current_user_rejects_missing_cookie PASSED
tests/test_auth_dependencies.py::test_get_current_user_accepts_valid_session PASSED
tests/test_auth_dependencies.py::test_require_csrf_rejects_missing_header PASSED
tests/test_auth_models.py::test_create_and_get_user PASSED
tests/test_auth_models.py::test_login_attempt_lockout PASSED
tests/test_auth_models.py::test_pending_login_roundtrip PASSED
tests/test_auth_models.py::test_pending_login_expires PASSED
tests/test_auth_models.py::test_pending_login_max_attempts PASSED
tests/test_auth_models.py::test_session_roundtrip PASSED
tests/test_auth_routes.py::test_login_flow_success PASSED
tests/test_auth_routes.py::test_login_wrong_password PASSED
tests/test_auth_routes.py::test_login_lockout_after_repeated_failures PASSED
tests/test_auth_routes.py::test_login_verify_wrong_code PASSED
tests/test_auth_routes.py::test_logout_clears_session PASSED
tests/test_config.py::test_settings_load_from_env PASSED
tests/test_config.py::test_healthz PASSED
tests/test_db.py::test_init_db_creates_tables PASSED
tests/test_security.py::test_password_hash_roundtrip PASSED
tests/test_security.py::test_verify_password_with_malformed_hash_returns_false PASSED
tests/test_security.py::test_totp_roundtrip PASSED
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username PASSED

21 passed, 67 warnings in 2.26s
```

All warnings are pre-existing deprecation notices (pydantic v1-style `Config` class, `asyncio.iscoroutinefunction`, FastAPI's `@app.on_event`) unrelated to this task's correctness; none are errors.

## Deviations from the brief

**One deviation, in the test file only — `app/auth/routes.py` and `app/main.py` are implemented exactly as the brief specifies, byte-for-byte.**

- **What:** In `tests/test_auth_routes.py`, `_setup_app` returns `TestClient(app, base_url="https://testserver")` instead of the brief's verbatim `TestClient(app)`.
- **Why:** The brief's login/verify routes correctly set `secure=True` on the `pending_token`, `session_token`, and `csrf_token` cookies, per the project's global constraint that session tokens must be handled as sensitive (the container sits behind a TLS-terminating Cloudflare Tunnel, so cookies are genuinely delivered over HTTPS in production). Starlette's `TestClient` defaults to `base_url="http://testserver"`, and httpx's cookie jar (correctly, per RFC 6265) refuses to replay `Secure`-flagged cookies on a subsequent request over a non-`https` origin. With the verbatim `TestClient(app)`, the `pending_token` cookie set by `/login` was silently dropped before the `/login/verify` call, causing `test_login_flow_success` and `test_logout_clears_session` to fail with 401s — not because the route logic was wrong, but because the test transport couldn't carry a `Secure` cookie over `http://`.
- **Investigation:** I confirmed this precisely by hand — writing a small script that made the same login → verify calls directly, first showing `req.headers.get('cookie')` was `None` on the second request under `http://testserver`, then showing the cookie is stored and correctly replayed once `base_url="https://testserver"` is used instead. Verified pinned versions (`fastapi==0.115.0` → `starlette==0.38.6`, `httpx==0.27.2`) match `requirements.txt`/`requirements-dev.txt` exactly, so this isn't a version-drift artifact — it reproduces in the exact environment the brief targets.
- **Alternative considered and rejected:** Weakening the routes (e.g., dropping `secure=True` or making it conditional) to make the verbatim test pass. Rejected because it would violate the brief's own security intent for session/pending/CSRF cookies and the project's global constraint that sessions must be handled as opaque, protected tokens — the test harness should adapt to correct security behavior, not the reverse.
- **Scope of the change:** One line, isolated to the test helper; no production code changed to accommodate this. `app/auth/routes.py` and the `app/main.py` router-mounting/startup-event code match the brief exactly.
