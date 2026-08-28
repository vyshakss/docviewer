# Final Review Fixes Report

This report covers the consolidated fix wave applied after the whole-project
final review, addressing all 10 items. Applied one at a time, with the
relevant test subset run after each before moving on. Full suite run at the
end.

Baseline before any fixes: 64 tests passed.
Final: **73 tests passed**, 0 failed.

---

## Fix 1 — TOTP verify had no effective rate limit

**File:** `app/auth/routes.py` (`login_verify`)

Previously, a failed TOTP guess was only tracked via the pending-login's own
`attempts` counter (max 5), which resets on every fresh `/login` call.
`is_locked_out()` was never consulted in this route, so an attacker who
already had the password could brute-force the 6-digit TOTP code with no
real per-account/IP throttle (just re-`/login` every 5 guesses).

Change: after resolving `user` from `row["user_id"]`, the route now:
1. Checks `models.is_locked_out(user["username"], ip, settings.login_lockout_threshold, settings.login_lockout_window_seconds)` and raises `429` if locked out — same pattern as `login`.
2. On a wrong TOTP code, calls both `models.increment_pending_login_attempts(pending_token)` (existing) **and** `models.record_login_attempt(user["username"], ip, success=False)` (new), so failed TOTP attempts now count toward the same lockout ledger as failed password attempts.

Used the existing `_client_ip(request)` helper, matching `login`'s pattern
exactly.

**Test added:** `tests/test_auth_routes.py::test_login_verify_lockout_after_repeated_totp_failures` — does 5 full `/login` + wrong-code `/login/verify` cycles, then confirms the 6th `/login` call itself returns 429.

Verified: `tests/test_auth_routes.py` — 8 passed.

---

## Fix 2 — FastAPI auto-docs publicly reachable + CDN JS in `/docs`

**File:** `app/main.py`

Changed:
```python
app = FastAPI(title="docviewer", docs_url=None, redoc_url=None, openapi_url=None)
```

Verified directly with `TestClient`: `/docs`, `/redoc`, `/openapi.json` all
return 404. Also added a permanent regression test,
`tests/test_config.py::test_docs_endpoints_disabled`.

---

## Fix 3 — No `Cache-Control` header on private file responses

**File:** `app/main.py` (`security_headers` middleware)

Added `response.headers["Cache-Control"] = "no-store"` alongside the
existing header assignments, applied to every response (including
`/api/download` and `/view`).

**Test added:** `tests/test_config.py::test_responses_include_no_store_cache_control`.

---

## Fix 4 — Outdated dependencies with known DoS CVEs

**File:** `requirements.txt`

```
fastapi==0.115.0        -> fastapi>=0.115.3
python-multipart==0.0.12 -> python-multipart>=0.0.18
(new)                     starlette>=0.40.0
```

Ran `.venv/bin/pip install -r requirements-dev.txt --upgrade`. Pip resolved
to (well above the stated minimums, since no upper bound was pinned):

```
fastapi           0.141.1
starlette         1.6.0
python-multipart  0.0.32
```

Full test suite re-run after the upgrade: all passed (this predates the
later fixes in this wave — I re-ran the full suite again at the very end
with everything applied, also all green). No breakage from the dependency
bump — the only user-visible change was cosmetic deprecation-warning noise
(`on_event` deprecated in favor of lifespan handlers, `httpx`-backed
`TestClient` deprecation notice) — both pre-existing patterns in this
codebase, not regressions from this fix, and out of scope for this fix wave.

---

## Fix 5 — Unauthenticated multipart parsing before auth dependency resolves

**File:** `app/main.py` (`security_headers` middleware)

Added an early rejection at the top of the middleware, before `call_next`:
if the request is a `POST` and has a `Content-Length` header whose value
(parsed defensively — a non-numeric header is treated as absent rather than
crashing the middleware) exceeds `get_settings().max_upload_bytes`, return
`413` immediately without invoking the route/dependency chain.

```python
if request.method == "POST":
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            content_length_bytes = int(content_length)
        except ValueError:
            content_length_bytes = None
        if content_length_bytes is not None and content_length_bytes > get_settings().max_upload_bytes:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
```

**Tests added** in `tests/test_config.py`:
- `test_oversized_content_length_rejected_before_routing` — crafts a `Content-Length` header exceeding `max_upload_bytes` with a small actual body, confirms `413`.
- `test_normal_small_post_still_works` — confirms an ordinary small `/login` POST still reaches the route (gets a normal `401` for bad credentials, not `413`).

As noted in the brief, this doesn't stop a chunked-transfer request with no
`Content-Length` header — that's an accepted limitation of this blunt guard,
matching the brief's own caveat.

---

## Fix 6 — `:U,Z` on the files volume would chown/relabel the user's real document collection

**File:** `docviewer.container`, `README.md`

Changed the files volume line only (state/state-cache left as `:U,Z`):

```diff
 [Container]
 Image=localhost/docviewer:local
 PublishPort=127.0.0.1:8000:8000
+UserNS=keep-id:uid=1000,gid=1000
-Volume=%h/docviewer-data/files:/data/files:U,Z
+Volume=%h/docviewer-data/files:/data/files:z
 Volume=%h/docviewer-data/state:/data/db:U,Z
 Volume=%h/docviewer-data/state-cache:/data/cache:U,Z
```

`UserNS=keep-id:uid=1000,gid=1000` maps the container's uid/gid 1000
(`appuser`) directly onto the *invoking host user's* uid/gid, instead of
through the usual subuid-mapped range — so `appuser` gets real read/write
access to files the host user already owns, with no recursive `chown` of
the source tree needed. Lowercase `:z` applies a shared SELinux label
(appropriate since the files directory may be touched by other things —
Samba, backups, a desktop file manager — unlike state/state-cache which
are exclusively docviewer's own).

**README.md** (`### A note on the volume flags` section, renamed from
`:U,Z` since the flags now differ per-volume) was rewritten to explain:
- the general meaning of `:U` and `:Z`/`:z` (kept from the original),
- that `state`/`state-cache` keep `:U,Z` because they're dedicated,
  app-only directories,
- that `files` deliberately avoids `:U`/`:Z` specifically to prevent
  Podman from recursively chowning/relabeling the user's pre-existing
  document collection on first start, and how `UserNS=keep-id` covers the
  UID-mapping need instead.

### Verification performed

The Quadlet generator binary is present on this machine
(`/usr/lib/systemd/user-generators/podman-user-generator`, confirmed via
`find`). I copied the updated `docviewer.container` into a scratch source
dir and ran the generator directly:

```
QUADLET_UNIT_DIRS=<scratch-src> /usr/lib/systemd/user-generators/podman-user-generator -v <scratch-out> <scratch-out> <scratch-out>
```

It exited 0 with no warnings/errors and produced `docviewer.service`,
whose generated `ExecStart` confirms the translation is exactly as
intended:

```
ExecStart=/usr/bin/podman run --name systemd-%N --replace --rm --cgroups=split --sdnotify=conmon -d \
  --userns keep-id:uid=1000,gid=1000 \
  -v %h/docviewer-data/files:/data/files:z \
  -v %h/docviewer-data/state:/data/db:U,Z \
  -v %h/docviewer-data/state-cache:/data/cache:U,Z \
  --publish 127.0.0.1:8000:8000 \
  --env-file %h/docviewer-data/docviewer.env \
  localhost/docviewer:local
```

This confirms: `UserNS=` translates to `--userns keep-id:...` correctly,
the files volume has `z` (no `U`), and the state/state-cache volumes are
unchanged with `U,Z`.

### What was **not** verified (concern for Fix 6)

I did **not** do a live re-run against a real, pre-existing document tree
owned by a different/real account to confirm end-to-end that `keep-id`
actually grants `appuser` read/write access to files it doesn't chown,
under real enforcing SELinux, the way Task 18's report did for the original
`:U,Z` combination (that report ran an actual `podman run` + wrote a file +
inspected ownership/SELinux type). I don't have a disposable "pre-existing
document collection owned by another account" to safely test against in
this environment without either using real user data or fabricating a
scenario that wouldn't prove much more than the static generator check
already did. The static Quadlet-syntax verification above is solid (proves
the unit parses and translates as intended), but the *runtime* behavior of
`keep-id` against a real foreign-owned tree under enforcing SELinux is
unverified here. I flagged this explicitly in the new README text
("A full live re-verification... was not performed in this environment and
should be done once on the real deployment target before relying on it with
irreplaceable data.").

---

## Fix 7 — `upload_file` had no guard around filesystem write calls

**File:** `app/files/routes.py`

Confirmed the failure mode first: a 250-character filename (well within the
route's own filename validation) produces a `.{filename}.part` temp name of
256 bytes, which exceeds this filesystem's `NAME_MAX` (255) —
`open()` raises `OSError: [Errno 36] File name too long`, previously
unhandled -> 500.

Wrapped the `open`/write-loop/`os.replace` sequence in
`try/except HTTPException: raise` / `except (OSError, ValueError):`,
matching the established pattern in `rename_file`/`move_file`/`delete_file`.
On `OSError`/`ValueError`, cleans up any partial temp file (itself wrapped
in its own `try/except OSError: pass`, since `Path.unlink(missing_ok=True)`
does **not** suppress `ENAMETOOLONG` — only `FileNotFoundError` — so a naive
single-layer cleanup would itself raise) and returns
`HTTPException(400, "Invalid filename or upload failed")`. The existing
`413`-for-oversize `HTTPException` raised from inside the `try` block is
re-raised untouched via the `except HTTPException: raise` clause.

**Test added:** `tests/test_files_routes.py::test_upload_long_filename_does_not_500` — uploads a 250-character filename, asserts the response is never `500`; on this filesystem it now returns `400` (kept the assertion filesystem-agnostic: if a future filesystem tolerates the longer temp name and returns `200`, the test verifies the file was actually written correctly instead).

---

## Fix 8 — `encodePath()` missing on the PDF.js viewer link

**File:** `app/static/app.js`

```diff
-window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent("/view/" + fullPath)}`, "_blank");
+window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent("/view/" + encodePath(fullPath))}`, "_blank");
```

The outer `encodeURIComponent` is untouched (still correct/necessary since
this whole string becomes one query-param value); only the inner path
segment encoding was fixed to match the pattern already used for
download/delete. No automated JS test infrastructure exists in this project
(all tests are Python/pytest against the backend), so this was a manual
code fix verified by inspection and by symmetry with the two other call
sites (`deleteEntry`, `openEntry`'s download branch) that already use
`encodePath`.

---

## Fix 9 — Test coverage gaps

1. **`test_logout_clears_session`** (`tests/test_auth_routes.py`): now
   captures the session cookie value *before* calling `/logout`, then
   replays it directly via a `Cookie` header against `GET /app` and asserts
   `401` — proving the session was actually invalidated server-side, not
   just that the client's cookie jar got cleared.

2. **`tests/test_files_routes.py::test_download_requires_auth`** (new):
   confirms `GET /api/download/{path}` returns `401` unauthenticated —
   previously untested despite being the most sensitive read route.

3. **`tests/test_preview_routes.py::test_view_rejects_traversal`** (new):
   confirms `GET /view/%2e%2e/%2e%2e/etc/passwd` (percent-encoded so the
   literal `..` bytes survive client-side RFC 3986 normalization) returns
   `400`.

4. **`tests/test_auth_routes.py::test_expired_session_rejected_at_route_level`**
   (new): creates a session directly via `models.create_session(user["id"], ttl_seconds=-1)`,
   sets it as the `session_token` cookie via a `Cookie` header, and confirms
   `GET /app` returns `401` — verifying expiry enforcement at the actual
   route/dependency level, complementing the existing model-level coverage
   in `tests/test_auth_models.py`.

(Also switched the cookie-replay technique in both new/updated tests from
httpx's per-request `cookies=` kwarg — which triggers a
`DeprecationWarning` in the installed httpx — to a plain `Cookie` header,
avoiding new warning noise.)

---

## Fix 10 — Unused `Settings.session_secret`

**Decision: removed the field entirely** (not just commented as
unused/reserved). Reasoning:
- Grepped the whole app package (`app/`) for any read of `session_secret` —
  none. Sessions are opaque, random, DB-backed tokens (`secrets.token_urlsafe(32)`
  hashed with SHA-256 for storage); nothing in the codebase signs or verifies
  anything with it.
- It was a **required** field with no default, meaning every deployment and
  every test had to supply a value that does nothing — actively misleading
  ("this must be a real secret" implies cryptographic use that doesn't
  exist).
- No forward-looking use was documented or planned anywhere in `.sdd/`
  beyond the review note itself, so "reserved for future use" would be
  speculative. If a real signing/CSRF-secret need arises later, adding the
  field back with a clear purpose comment costs nothing.

Changes:
- `app/config.py`: removed `session_secret: str` field.
- `tests/test_config.py`: removed the `SESSION_SECRET` env var setup and the
  `assert settings.session_secret == ...` line from `test_settings_load_from_env`;
  removed now-pointless `monkeypatch.setenv("SESSION_SECRET", ...)` calls
  from the newly-added tests in this fix wave too.
- `tests/test_auth_routes.py`, `tests/test_files_routes.py`,
  `tests/test_preview_routes.py`: removed all `monkeypatch.setenv("SESSION_SECRET", ...)`
  calls (verified via `Settings()` construction that unmapped extra env vars
  are silently ignored by pydantic-settings, so leaving them would not have
  broken anything — this is pure cleanup, not a required change).
- `.env.example`: rewritten — no `SESSION_SECRET` line; explains the
  deployed container currently has **no required** environment variables at
  all (paths are baked in via `Containerfile` `ENV`), and that the file/its
  copy can stay empty since `EnvironmentFile=` in `docviewer.container`
  still expects the file to exist.
- `README.md`: updated the deploy step 3 (no longer instructs generating a
  `SESSION_SECRET`) and the local-dev `cp .env.example .env` comment (now
  lists only `FILES_ROOT/DB_PATH/CACHE_DIR`).
- `docviewer.container`, `Containerfile`: no references existed to remove.

---

## Full test suite

```
$ .venv/bin/pytest -v
...
73 passed, 4 warnings in 8.84s
```

All 73 tests pass (64 baseline + 9 new: TOTP-verify lockout, docs-disabled,
no-store cache-control, oversized-content-length-413, normal-small-post,
upload-long-filename, download-requires-auth, view-rejects-traversal,
expired-session-at-route-level).

Remaining warnings are pre-existing and unrelated to this fix wave:
- `on_event is deprecated, use lifespan event handlers instead` (FastAPI)
- `Using httpx with starlette.testclient is deprecated; install httpx2 instead`
- `Support for class-based config is deprecated, use ConfigDict instead` (Pydantic)

None of these were introduced by this fix wave; left as-is since fixing them
wasn't in scope for the 10 listed fixes.

---

## Files touched

- `app/main.py` — Fix 2, 3, 5
- `app/auth/routes.py` — Fix 1
- `app/files/routes.py` — Fix 7
- `app/config.py` — Fix 10
- `app/static/app.js` — Fix 8
- `requirements.txt` — Fix 4
- `docviewer.container` — Fix 6
- `README.md` — Fix 6, Fix 10
- `.env.example` — Fix 10
- `tests/test_auth_routes.py` — Fix 1, 9, 10 (cleanup)
- `tests/test_config.py` — Fix 2, 3, 5, 10
- `tests/test_files_routes.py` — Fix 7, 9, 10 (cleanup)
- `tests/test_preview_routes.py` — Fix 9, 10 (cleanup)

## Judgment calls summary

- **Fix 5**: hardened the `Content-Length` parse with a `try/except ValueError`
  beyond what the brief's example snippet showed, so a malformed header
  can't itself crash the pre-auth middleware with a 500.
- **Fix 6**: chose `UserNS=keep-id:uid=1000,gid=1000` + `:z` exactly as the
  brief specified; could not perform a live runtime re-verification against
  a real foreign-owned document tree in this environment (no podman-in-CI
  root access pattern set up for that, and fabricating one wouldn't
  meaningfully exceed what the static generator check already proved) — see
  the dedicated concern note above and in the updated README.
- **Fix 7**: added a second nested `try/except OSError: pass` around the
  cleanup `unlink()` call, beyond the brief's literal instruction, because
  testing revealed `missing_ok=True` does not suppress `ENAMETOOLONG` (only
  `FileNotFoundError`), so a single-layer guard would itself have raised an
  unhandled 500 on exactly the filename-too-long case this fix targets.
- **Fix 10**: chose full removal over keeping-with-comment, per the brief's
  stated default preference, with reasoning given above.
