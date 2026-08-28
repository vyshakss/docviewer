# Task 14 Report — Frontend: login page

## Files created/modified

- **Created** `app/static/login.html` — password + TOTP forms, verbatim from the brief (Step 1). Links `/static/app.css` (not yet created — that file is created in Task 15's `app.css`; a 404 for that stylesheet is expected at this point in the plan and does not affect functionality, only styling).
- **Created** `app/static/login.js` — verbatim from the brief (Step 2). Handles submit on `#password-form` (POST `/login`) and `#totp-form` (POST `/login/verify`).
- **Modified** `app/main.py`:
  - Added imports: `FileResponse` (added to the existing `from fastapi.responses import JSONResponse` line, now `from fastapi.responses import FileResponse, JSONResponse`) and `from fastapi.staticfiles import StaticFiles`.
  - Added `app.mount("/static", StaticFiles(directory="app/static"), name="static")` immediately after the three existing `app.include_router(...)` calls.
  - Added `GET /` route (`login_page`) returning `FileResponse("app/static/login.html")`.
  - Left the rest of the file (security-headers middleware, `/healthz`, startup event) untouched — only additive changes, no rewrite.

No other files were changed. `app/static/` did not exist before this task; it was created fresh.

## Verification performed

Could not do the brief's literal browser-based manual verification (non-interactive agent, no browser). Instead did the following, all via FastAPI's `TestClient` (httpx-backed), using the same env-var/DB setup pattern as `tests/test_auth_routes.py::_setup_app` (temp `FILES_ROOT`/`DB_PATH`/`CACHE_DIR`, `get_settings.cache_clear()`, `db.reset_conn_for_tests()`, `db.init_db()`, a user created via `app.auth.models.create_user`, `TestClient(app, base_url="https://testserver")` so Secure-flagged cookies are stored/replayed).

Ran as a one-off script (not added to the pytest suite, per the brief note that this task has no pytest tests) at
`/tmp/claude-1000/-run-media-vyshak-ssd/b4e34e93-ca39-4fb5-a377-02097f2e2a31/scratchpad/verify_task14.py`. Output — all 16 checks passed:

```
[PASS] GET /static/login.html -> 200
[PASS] GET /static/login.html content matches file on disk
[PASS] GET /static/login.js -> 200
[PASS] GET /static/login.js content matches file on disk
[PASS] GET /static/login.js content-type is javascript
[PASS] GET / -> 200
[PASS] GET / body matches login.html
[PASS] POST /login -> 200
[PASS] POST /login response has requires_totp True
[PASS] pending_token cookie set after /login
[PASS] POST /login/verify -> 200
[PASS] POST /login/verify response has ok True
[PASS] session_token cookie set after /login/verify
[PASS] csrf_token cookie set after /login/verify
[PASS] POST /login wrong password -> 401
[PASS] 401 response body has 'detail' field (login.js reads body.detail)

ALL CHECKS PASSED
```

This covers:
1. `/static/login.html` and `/static/login.js` are served with status 200 and byte-identical content to what's on disk (login.js served with a JavaScript content-type via `StaticFiles`).
2. `GET /` returns exactly the `login.html` content (the brief's login page at `/`).
3. A full simulated login: `POST /login` with correct credentials returns 200 + `{"requires_totp": true}` and sets a `pending_token` cookie; `POST /login/verify` with a valid TOTP code (`pyotp.TOTP(secret).now()`) returns 200 + `{"ok": true}` and sets both `session_token` and `csrf_token` cookies — proving the backend the JS talks to actually issues a working session.
4. A negative case (wrong password) returns 401 with a `detail` field present, matching what `login.js`'s error handler reads.

Also ran the full existing pytest suite to confirm no regression: `python -m pytest -q` → **63 passed**, 0 failed (only pre-existing deprecation warnings unrelated to this change, e.g. `on_event` deprecation, Pydantic v2 config deprecation).

## Manual code trace of `login.js` vs. `app/auth/routes.py`

Read `app/auth/routes.py` in full and cross-checked every URL, HTTP method, and JSON field name used in `login.js`:

| login.js usage | Backend (`app/auth/routes.py`) | Match? |
|---|---|---|
| `fetch("/login", { method: "POST", ... })` with JSON body `{username, password}` | `@router.post("/login")` takes `LoginBody(username: str, password: str)` | Matches |
| On non-ok: reads `body.detail` | `HTTPException(status_code=401/429, detail="...")` — FastAPI serializes this as `{"detail": "..."}` | Matches |
| On ok: hides password form, shows TOTP form (does not inspect the response body at all, e.g. doesn't check `requires_totp`) | `/login` on success always returns `{"requires_totp": true}` and sets `pending_token` cookie via `Set-Cookie` (httponly, secure, samesite=strict) | Consistent — since `/login` only ever returns 200 on success with `requires_totp: true` (no branch where success returns something else), not reading that field isn't a bug, just doesn't discriminate — acceptable for a single-user app where TOTP is always required |
| `fetch("/login/verify", { method: "POST", ... })` with JSON body `{code}` | `@router.post("/login/verify")` takes `VerifyBody(code: str)`, reads `pending_token` from cookies | Matches |
| On non-ok: reads `body.detail` | Same `HTTPException(..., detail=...)` pattern (401 for missing/expired pending login, invalid code) | Matches |
| On ok: `window.location.href = "/app"` | `/login/verify` returns `{"ok": true}` and sets `session_token` + `csrf_token` cookies; redirect target `/app` is created in Task 15 (currently 404, expected per brief) | Matches |
| No explicit `credentials` option on either `fetch()` call | `/login` sets `pending_token` cookie; `/login/verify` needs to read it back | Not a bug: per the Fetch spec, the default `credentials` mode for same-origin requests is `"same-origin"`, so the browser sends the `pending_token` cookie automatically on the same-origin `/login/verify` call without needing `credentials: "include"`. Verified this is the actual current spec/browser behavior (not the older `"omit"` default from early Fetch drafts). |
| CSRF: neither form's fetch sends an `X-CSRF-Token` header | `/login` and `/login/verify` are unauthenticated bootstrap routes (no `Depends(get_current_user)`, no CSRF check in the route bodies) — CSRF-header enforcement per the project's global constraints applies to authenticated mutating routes, not to establishing the session itself | Consistent, not a bug for this task's scope |

**No field-name or URL mismatches found.** The JS and backend agree on every route, HTTP verb, request field name, and error field name involved in the login/TOTP flow.

## Known non-issues (in-scope for later tasks, not bugs in Task 14)

- `login.html`'s `<link rel="stylesheet" href="/static/app.css">` 404s until Task 15 creates `app/static/app.css`. This matches the brief's own file list (Task 15 creates `app.css`) — not a defect introduced here.
- Successful login redirects to `/app`, which 404s until Task 15 creates that route/page. The brief explicitly calls this out as expected at this stage.

## Summary

No bugs found in the brief's `login.js`/`login.html` code as written — it was implemented verbatim per the brief and independently verified against the real backend field names in `app/auth/routes.py`. The only edits made beyond the brief's literal file contents were the additive changes to `app/main.py` (imports, static mount, `/` route), inserted without disturbing existing code. Full pytest suite (63 tests) still passes.
