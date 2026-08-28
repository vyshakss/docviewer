# Task 9 Report — File listing and download

## Files created/modified

- **Created** `app/files/routes.py` — new `router = APIRouter(prefix="/api")` with:
  - `GET /api/files?path=` — lists directory entries (`name`, `is_dir`, `size`, `mtime`).
  - `GET /api/download/{path:path}` — streams a file back via `FileResponse`.
  - Both depend on `app.auth.dependencies.get_current_user` (401 if unauthenticated) and route all
    user-supplied paths through `app.files.pathutils.resolve_safe_path` (400 on `UnsafePathError`).
- **Modified** `app/main.py` — imported `app.files.routes.router as files_router` and added
  `app.include_router(files_router)` after the existing `app.include_router(auth_router)` line.
  Nothing else in the file was touched.
- **Created** `tests/test_files_routes.py` — the brief's four tests: `test_list_root_directory`,
  `test_list_requires_auth`, `test_list_rejects_traversal`, `test_download_file`. One line was
  changed from the brief's verbatim listing (see Deviations below).

## TDD steps followed

1. Wrote `tests/test_files_routes.py` exactly as given in the brief (Step 1).
2. Ran `.venv/bin/pytest tests/test_files_routes.py -v` before creating `app/files/routes.py`.
   Result: 4 failed. (All four requests 404'd because no route existed at `/api/files` or
   `/api/download/...` — FastAPI's default 404 for an unmatched path — rather than a
   `ModuleNotFoundError`, since the test file itself doesn't import `app.files.routes` directly;
   the *effect* the brief anticipated — "route module doesn't exist yet" — was confirmed.)
3. Wrote `app/files/routes.py` per the brief, with the OSError defense-in-depth addition (see
   below).
4. Mounted the router in `app/main.py`.
5. Re-ran the test file — 3 of 4 still failed (`test_list_requires_auth` passed immediately since
   it never authenticates). Diagnosed and fixed a test-fixture issue (see Deviations below), then
   all 4 passed.
6. Ran the full suite (`.venv/bin/pytest -q`): **30 passed**, confirming no regressions to the
   Task 1–8 auth/db/pathutils tests.

## Test commands and output

```
$ .venv/bin/pytest tests/test_files_routes.py -v
...
FAILED tests/test_files_routes.py::test_list_root_directory - assert 404 == 200
FAILED tests/test_files_routes.py::test_list_requires_auth - assert 404 == 401
FAILED tests/test_files_routes.py::test_list_rejects_traversal - assert 404 == ...
FAILED tests/test_files_routes.py::test_download_file - assert 404 == 200
4 failed, 36 warnings in 1.23s
```

(after writing `app/files/routes.py` and mounting it, before the test-fixture fix)

```
$ .venv/bin/pytest tests/test_files_routes.py -v
FAILED tests/test_files_routes.py::test_list_root_directory - assert 401 == 200
FAILED tests/test_files_routes.py::test_list_rejects_traversal - assert 401 == ...
FAILED tests/test_files_routes.py::test_download_file - assert 401 == 200
3 failed, 1 passed, 44 warnings in 1.30s
```

(after the test-fixture fix — `base_url="https://testserver"`)

```
$ .venv/bin/pytest tests/test_files_routes.py -v
4 passed, 39 warnings in 1.06s
```

(full suite)

```
$ .venv/bin/pytest -q
30 passed, 85 warnings in 2.83s
```

## Deviation from the brief: test client base_url

The brief's `_authed_client` helper (Step 1) does `client = TestClient(app)`, which defaults to
`base_url="http://testserver"`. Task 7's auth routes (`app/auth/routes.py`, already
reviewed/frozen) set `pending_token`, `session_token`, and `csrf_token` cookies with
`secure=True`. httpx's cookie jar (used by `TestClient`) will not attach a `Secure` cookie to a
subsequent request unless the request URL scheme is `https`, so with the plain `http://testserver`
base URL the `pending_token` cookie set by `POST /login` is silently dropped before
`POST /login/verify` is sent, `login/verify` responds 401 ("No pending login"), no
`session_token` is ever issued, and every downstream `/api/...` call correctly gets 401 from
`get_current_user`.

This is not a bug in `app/files/routes.py` — it's a property of the existing (already-reviewed)
Secure-cookie auth flow interacting with `TestClient`'s default scheme. `tests/test_auth_routes.py`
(Task 7) already works around exactly this by constructing its client with
`TestClient(app, base_url="https://testserver")`. I applied the same one-line fix to
`_authed_client` in `tests/test_files_routes.py`:

```python
client = TestClient(app, base_url="https://testserver")
```

(with a comment explaining why). `test_list_requires_auth`, which never logs in, was left as
`TestClient(app)` since it doesn't depend on cookies at all. No other line of the brief's test or
implementation code was changed.

## OSError defense-in-depth handling

Per the task instructions, `resolve_safe_path()` can, in one known edge case (a symlink loop
entirely inside `files_root`), let a raw `OSError` (`ELOOP`) escape from a *later* filesystem call
rather than raising `UnsafePathError` itself. I wrapped the filesystem-touching portions of both
routes in `try/except OSError`, converting any such error into the same clean `400 Invalid path`
response used for `UnsafePathError`:

- `list_files`: the `target.exists() / target.is_dir() / target.iterdir() / child.stat() /
  child.is_dir()` block is wrapped; an `OSError` there returns 400.
- `download_file`: the `target.exists() / target.is_dir()` check is wrapped; an `OSError` there
  returns 400.

The `HTTPException(404, ...)` raised for a legitimately missing path is *inside* the same `try`
block but is unaffected — `HTTPException` is not an `OSError` subclass, so it propagates through
the `except OSError` clause untouched and still yields the correct 404.

I verified this manually (outside the automated test suite, since the brief didn't ask for a new
test case here and the note said "don't over-engineer it"):

- A directory containing a self-referential symlink (`looplink -> looplink`) sitting inside
  `files_root`: `GET /api/files?path=` (listing the parent, which iterates the loop as a child and
  calls `child.stat()` on it) returned `400 {"detail": "Invalid path"}` instead of crashing with an
  unhandled 500/`OSError` traceback. Without the `except OSError` wrapper this same request raises
  `OSError: [Errno 40] Too many levels of symbolic links` uncaught by FastAPI's default exception
  handling path (i.e. it would surface as a 500).
- A deeply nested (20-level) walk through a self-referential directory symlink as the `path`
  parameter itself resolved and listed successfully (200) — `resolve_safe_path`'s underlying
  `Path.resolve()` handled that particular shape of loop without raising, and subsequent
  `exists()`/`is_dir()` calls on the fully-resolved target are internally OSError-safe in this
  Python version (they call `os.path.exists`/`os.path.isdir`, which swallow `OSError` and return
  `False`) — so 404 is the natural (and correct) outcome there rather than needing the new
  wrapper. The wrapper is what catches the case that *isn't* naturally safe: `Path.stat()` (used
  for each directory entry's size/mtime) does **not** swallow `OSError`, which is exactly the gap
  this task asked me to close.

No new automated test was added for this edge case since the brief's Step 1 test file was to be
used verbatim (aside from the base_url fix above) and the instructions described this as a small,
non-exploitable defense-in-depth measure not requiring its own test. If a dedicated regression
test is wanted later, `tests/test_files_routes.py` is the natural home for it.

## Other notes

- No changes were made to `app/files/pathutils.py`, `app/auth/*`, `app/config.py`, or `app/db.py`.
- `app/main.py`'s only change is the two-line router import + mount shown above; the startup
  handler, security-headers middleware, and `/healthz` route are untouched.
- Full repo test suite: 30 passed, 0 failed, 0 skipped (only pre-existing `DeprecationWarning`s
  from FastAPI's `on_event`, unrelated to this task).
