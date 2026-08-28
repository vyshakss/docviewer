# Task 13 Report: Preview route (`/view/{path}`)

## Summary

Implemented the preview route that serves PDFs directly and converts
`.doc`/`.docx` files to PDF (via `app.preview.convert.get_preview_pdf`) before
serving them. All filesystem paths derived from the `path` URL parameter go
through `resolve_safe_path(settings.files_root, path)` before any
existence/type check or use as `convert.py`'s `source` argument, so
`convert.py`'s trust assumption (that `source` has already been validated) is
honored — the raw `path` string is never passed to `get_preview_pdf` or used
in any filesystem call.

## Files created/modified

1. **Created** `/run/media/vyshak/ssd/docviewer/app/preview/routes.py`
   - `router = APIRouter()` with `GET /view/{path:path}`.
   - Depends on `get_current_user` (auth required, 401 if not authenticated
     — enforced by the existing dependency, not custom logic here).
   - Resolves `path` via `resolve_safe_path(settings.files_root, path)`,
     catching `UnsafePathError` → 400.
   - 404 if the resolved target doesn't exist or isn't a file.
   - `.pdf` → streamed directly via `FileResponse(target, media_type="application/pdf")`.
   - `.docx`/`.doc` → calls `get_preview_pdf(target, settings.cache_dir)`,
     catching `ConversionError` → 502, then serves the returned cached PDF.
   - Anything else → 415 Unsupported preview type.
   - Matches the brief's Step 3 code verbatim.

2. **Modified** `/run/media/vyshak/ssd/docviewer/app/main.py`
   - Added `from app.preview.routes import router as preview_router`.
   - Added `app.include_router(preview_router)` after the files router.
   - No other changes — existing auth/files routers, startup hook,
     security-headers middleware, and `/healthz` route left untouched.

3. **Created** `/run/media/vyshak/ssd/docviewer/tests/test_preview_routes.py`
   - 4 tests per the brief: PDF streamed directly, docx converted via mocked
     `get_preview_pdf`, unsupported type → 415, unauthenticated request → 401.
   - One deviation from the brief's literal test code — see below.

## Deviation from the brief (with reasoning)

The brief's Step 1 test code instantiates the authenticated client as
`TestClient(app)` (default base URL `http://testserver`). Running that
exact code failed: `test_view_pdf_streams_directly`,
`test_view_docx_converts_via_cache`, and `test_view_unsupported_type_returns_415`
all got `401` instead of their expected status, because the login flow never
actually authenticated the client.

Root cause: `app/auth/routes.py` sets `session_token`, `csrf_token`, and
`pending_token` cookies with `secure=True` (by design — Task 12 hardening).
httpx's cookie jar (which `TestClient` wraps) will not store `Secure`-flagged
cookies for a plain `http://` base URL, so the session cookie set by
`/login/verify` was silently dropped and every subsequent request was
unauthenticated. The already-reviewed `tests/test_auth_routes.py` works
around exactly this by instantiating
`TestClient(app, base_url="https://testserver")`, with a comment explaining
why.

Fix applied: changed the one line in `_authed_client()` in
`tests/test_preview_routes.py` from `TestClient(app)` to
`TestClient(app, base_url="https://testserver")`, matching the established
convention in `test_auth_routes.py`, and added the same explanatory comment.
This is the only change from the brief's literal test code; the unauthenticated
test (`test_view_requires_auth`) was left using plain `TestClient(app)` since
it doesn't rely on cookies surviving and matches the brief exactly (it passed
as-is).

No other deviations. The implementation file (`app/preview/routes.py`) and
the `app/main.py` router-mount were written exactly as specified in the brief.

## Test commands and output

### Step 2: confirm the test fails before implementation

```
$ source .venv/bin/activate && pytest tests/test_preview_routes.py -v
...
FAILED tests/test_preview_routes.py::test_view_pdf_streams_directly - assert ...
FAILED tests/test_preview_routes.py::test_view_docx_converts_via_cache - AttrError...
FAILED tests/test_preview_routes.py::test_view_unsupported_type_returns_415
FAILED tests/test_preview_routes.py::test_view_requires_auth - assert 404 == 401
4 failed, 59 warnings in 1.31s
```
(Failures were 404s from the router not existing yet / app.preview.routes not
mounted — equivalent in effect to the brief's expected
`ModuleNotFoundError`, since `app/main.py` didn't yet import `app.preview.routes`
and no `/view/*` route existed.)

### After writing `app/preview/routes.py` and mounting it, before the test client fix

```
$ pytest tests/test_preview_routes.py -v
FAILED tests/test_preview_routes.py::test_view_pdf_streams_directly - assert 401 == 200
FAILED tests/test_preview_routes.py::test_view_docx_converts_via_cache - assert 401 == 200
FAILED tests/test_preview_routes.py::test_view_unsupported_type_returns_415 - assert 401 == 415
PASSED tests/test_preview_routes.py::test_view_requires_auth
3 failed, 1 passed, 64 warnings in 1.30s
```
This confirmed the route implementation itself was correct (auth-gated,
would have returned the right codes) but the test's cookie handling was
broken — diagnosed and fixed as described above.

### Step 5: after the test-client fix

```
$ source .venv/bin/activate && pytest tests/test_preview_routes.py -v
tests/test_preview_routes.py::test_view_pdf_streams_directly PASSED
tests/test_preview_routes.py::test_view_docx_converts_via_cache PASSED
tests/test_preview_routes.py::test_view_unsupported_type_returns_415 PASSED
tests/test_preview_routes.py::test_view_requires_auth PASSED
4 passed, 59 warnings in 1.17s
```

### Step 6: full test suite

```
$ source .venv/bin/activate && pytest -v
...
63 passed, 185 warnings in 7.06s
```

All pre-existing tests (auth, files, pathutils, config, db, convert, security)
continue to pass alongside the 4 new preview-route tests. Warnings are
pre-existing deprecation notices (Pydantic v1-style `Config` class,
`@app.on_event`, `asyncio.iscoroutinefunction`) unrelated to this task.

## Security review notes (self-check against brief's constraints)

- `path` is only ever used as input to `resolve_safe_path(settings.files_root, path)`;
  the returned `target: Path` (not the raw string) is what's checked for
  existence/file-ness and passed to `get_preview_pdf` and `FileResponse`. This
  satisfies the "the source passed to convert.py must always be the
  resolve_safe_path result" requirement.
- `UnsafePathError` → 400, consistent with `app/files/routes.py`'s pattern.
- Route requires `get_current_user` (session auth) — no anonymous preview access.
- This is a `GET`-only route (no mutation), so no CSRF requirement applies,
  consistent with the global constraint that CSRF is required only for
  `POST`/`DELETE`.
- No new filesystem writes outside `settings.cache_dir` (handled entirely by
  `get_preview_pdf`, already audited in Task 11/12 scope).
