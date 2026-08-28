# Task 15 Report — Frontend: file browser page

## Files created/modified

- **Created** `app/static/app.css` — verbatim from the brief (Step 1).
- **Created** `app/static/index.html` — verbatim from the brief (Step 2). Header with breadcrumbs nav, upload/logout buttons, entries table, loads `/static/app.js`.
- **Created** `app/static/app.js` — brief's code (Step 3) with one deliberate fix (see "Bug found and fixed" below): a new `encodePath()` helper, and its use in the two places that build a URL *path* from a filename (`/api/download/...` and `DELETE /api/files/...`).
- **Modified** `app/main.py`:
  - Added `Depends` to the `fastapi` import line (`from fastapi import Depends, FastAPI`).
  - Added `from app.auth.dependencies import get_current_user`.
  - Added the `GET /app` route (`app_page`), gated with `Depends(get_current_user)`, returning `FileResponse("app/static/index.html")`, placed directly after the existing `GET /` route.
  - No other lines touched — security-headers middleware, `/healthz`, startup event, router mounts, and the Task 14 `/` route and static mount are all untouched.

## Verification performed

No pytest tests were added for this task (frontend HTML/JS/CSS, per instructions). Instead ran a one-off script (not collected by pytest) at
`/tmp/claude-1000/-run-media-vyshak-ssd/b4e34e93-ca39-4fb5-a377-02097f2e2a31/scratchpad/verify_task15.py`, using the same env-var/DB setup pattern as `tests/test_auth_routes.py::_setup_app` (temp `FILES_ROOT`/`DB_PATH`/`CACHE_DIR`, `get_settings.cache_clear()`, `db.reset_conn_for_tests()`, `db.init_db()`, a user via `app.auth.models.create_user`, `TestClient(app, base_url="https://testserver")` for Secure-cookie support).

Output — all 39 checks passed:

```
[PASS] GET /app unauthenticated -> 401
[PASS] GET /static/app.css -> 200
[PASS] app.css content-type is text/css
[PASS] GET /static/index.html -> 200
[PASS] index.html contains app.js script tag
[PASS] GET /static/app.js -> 200
[PASS] app.js contains loadEntries call
[PASS] POST /login -> 200
[PASS] requires_totp true
[PASS] POST /login/verify -> 200
[PASS] session_token cookie set
[PASS] csrf_token cookie set
[PASS] GET /app authenticated -> 200
[PASS] GET /app returns file-browser HTML (has #entries tbody)
[PASS] GET /app is index.html not login.html
[PASS] csrf_token readable (non-HttpOnly) like getCookie() expects
[PASS] GET /api/files?path= -> 200
[PASS] response has 'entries' key
[PASS] root dir starts empty
[PASS] POST /api/upload -> 200
[PASS] upload response ok:true
[PASS] upload response name matches
[PASS] uploaded file now listed
[PASS] entry has is_dir field (false)
[PASS] entry has size field matching content length
[PASS] entry has mtime field (numeric)
[PASS] POST /api/upload without CSRF header -> 403
[PASS] 403 body has 'detail' field (alert() reads .detail)
[PASS] POST /api/rename -> 200
[PASS] rename response ok:true
[PASS] renamed.txt present, old name gone
[PASS] upload tricky filename -> 200
[PASS] DELETE /api/files/weird%20name%20%231.txt (encodePath of tricky name) -> 200
[PASS] tricky-named file deleted
[PASS] DELETE /api/files/renamed.txt -> 200
[PASS] directory empty again
[PASS] DELETE without CSRF header -> 403
[PASS] POST /logout -> 200
[PASS] GET /app after logout -> 401

ALL CHECKS PASSED
```

This covers everything the task asked to verify programmatically:

1. **Auth gate on `/app`**: `GET /app` returns 401 with no session cookie, and 200 with the file-browser HTML (`id="entries"`, `breadcrumbs`) once a real session is established via the full login + TOTP flow — proving `Depends(get_current_user)` is wired correctly.
2. **Static files serve**: `/static/app.css` (text/css) and `/static/index.html` (contains the `/static/app.js` script tag) both return 200 through the existing `StaticFiles` mount from Task 14 — no changes needed there since it's a directory mount.
3. **Full simulated session exercising the real API contract app.js uses**: login → TOTP verify → `GET /api/files?path=` (list) → `POST /api/upload` (multipart, `file` field, `path` query param) → `POST /api/rename` (JSON body) → `DELETE /api/files/{path}` — every call using the `csrf_token` cookie read exactly the way `getCookie()`/`csrfHeaders()` do (`X-CSRF-Token` header), and additionally proving CSRF enforcement actually rejects unauthenticated-header requests (403) on both upload and delete, matching the brief's constraint that all mutating routes require both session + CSRF.
4. Also uploaded and deleted a file with a tricky name (`weird name #1.txt`, containing a space and a `#`) to directly exercise the `encodePath()` fix described below against the real `DELETE /api/files/{path:path}` route.

Also reran the full existing pytest suite to confirm no regression from the `app/main.py` edit: `python -m pytest -q` → **63 passed**, 0 failed (only pre-existing deprecation warnings, unrelated to this change).

## Code trace of `app.js` vs. the real backend (`app/files/routes.py`, `app/auth/routes.py`, `app/auth/dependencies.py`, `app/preview/routes.py`)

| app.js usage | Backend | Match? |
|---|---|---|
| `GET /api/files?path=${encodeURIComponent(path)}` | `@router.get("/files")` under `prefix="/api"`, `path: str = ""` query param | Matches |
| Reads `data.entries`, each entry's `.is_dir`, `.name`, `.size`, `.mtime` | Route returns `{"entries": [{"name", "is_dir", "size", "mtime"}, ...]}` | Matches. `is_dir` is a Python `bool` → JSON `true`/`false` → JS `boolean`; `renderEntries`'s `(b.is_dir - a.is_dir)` sort works because JS coerces booleans to 0/1 in arithmetic context — confirmed, not a bug. |
| `401` from `/api/files` → redirect to `/` | `get_current_user` raises `HTTPException(401, "Not authenticated")` when no/invalid session | Matches |
| `POST /api/upload?path=${encodeURIComponent(currentPath)}` with `FormData` field named `"file"` | `@router.post("/upload")` takes `file: UploadFile` (FastAPI binds an untyped `UploadFile` param to the multipart field of the same name) and `path: str = Query("")` | Matches |
| Upload headers: `csrfHeaders()` only (no `Content-Type` set manually) | Route requires `Depends(require_csrf)`; browser sets the correct `multipart/form-data; boundary=...` automatically when `body` is a `FormData` and no `Content-Type` header is manually set | Matches — setting `Content-Type` by hand here would actually break the multipart boundary, so its absence is correct, not an omission |
| On non-ok: `(await resp.json()).detail` | All `HTTPException`s here serialize to `{"detail": "..."}` | Matches |
| `POST /api/rename` JSON body `{path: fullPath, new_name: newName}` | `@router.post("/rename")` takes `RenameBody(path: str, new_name: str)` | Matches |
| `DELETE /api/files/${fullPath}` (**original brief code**, before fix) | `@router.delete("/files/{path:path}")` | See "Bug found and fixed" below |
| `logout-button` → `POST /logout` with `csrfHeaders()` | `@router.post("/logout")`, `Depends(get_current_user)` | Matches. Note: `logout` does **not** have `Depends(require_csrf)` in the current backend (only `get_current_user`), so the CSRF header app.js sends is currently not enforced on this one route. This is a pre-existing backend characteristic from an earlier, already-reviewed task, not a frontend/backend contract mismatch — app.js sending the header is harmless and forward-compatible if that route is ever hardened. Out of scope for this task's file list (`app/auth/routes.py` isn't listed as a Task 15 file), so left unchanged; flagging it here for visibility. |
| `openEntry()`: `.pdf`/`.docx`/`.doc` → `window.open(".../viewer.html?file=" + encodeURIComponent("/view/" + fullPath))` | `@router.get("/view/{path:path}")` in `app/preview/routes.py`, gated on `get_current_user`, serves `.pdf` directly and converts `.doc`/`.docx` via `get_preview_pdf` | Matches. `encodeURIComponent` on the whole `"/view/" + fullPath` string is correct here because it's used as a single opaque query-parameter *value* passed to pdfjs's viewer (which itself decodes and re-fetches it) — not as a literal URL path, so encoding the `/` characters too is fine. |
| `openEntry()`: text-like → `window.open("/static/viewer.html?path=" + encodeURIComponent(fullPath))` | `/static/viewer.html` doesn't exist yet (built in a later task per the brief's own Step 5 note) | Consistent with brief; out of scope. Query-param encoding here is correct for the same reason as above. |
| `openEntry()`: fallback → `window.open("/api/download/" + fullPath)` (**original brief code**, before fix) | `@router.get("/download/{path:path}")` | See "Bug found and fixed" below |

**No field-name or method mismatches** between app.js and the real backend routes. One real bug was found in URL construction (below) and fixed.

## Bug found and fixed

**Unencoded filenames interpolated directly into URL *path* segments.**

The brief's `app.js` builds two URLs by directly concatenating `fullPath` (a `/`-joined directory/filename string that can contain arbitrary characters — the backend only rejects `.`/`..`/embedded path separators/mismatched raw vs. `Path(...).name`, not spaces or URL-special characters) straight into the URL *path*, with no encoding at all:

```javascript
// download fallback in openEntry():
window.open(`/api/download/${fullPath}`, "_blank");

// deleteEntry():
const resp = await fetch(`/api/files/${fullPath}`, { method: "DELETE", headers: csrfHeaders() });
```

This is inconsistent with the rest of the same file, which correctly `encodeURIComponent`s `fullPath` everywhere it's used as a *query-parameter value* (`/api/files?path=`, `/api/upload?path=`, the pdfjs/`viewer.html` `?file=`/`?path=` params). Those two spots instead splice the raw string into the URL path itself. Since the backend's upload/rename routes happily accept filenames containing spaces or characters like `#`, `?`, `%`, `&`, `+` (they only validate against traversal, not against "URL-unsafe" characters), a user who uploads e.g. `weird name #1.txt` and then clicks Download, or clicks Delete, would get a broken request:

- `#` truncates the URL at the browser level before it's even sent (everything after becomes a fragment) — Download of such a file would silently request the wrong path.
- `?` would start a bogus query string, `%` not followed by two hex digits could produce a malformed URI, `+`/`&` etc. would also corrupt the intended filename.
- Spaces are usually auto-normalized by browsers on navigation, but the other characters above are not, so this wasn't just a cosmetic risk — it was a genuine breakage for a range of legal filenames the backend accepts.

**Fix**: added an `encodePath()` helper that percent-encodes each `/`-delimited segment independently (so real path separators are preserved as `/` while everything else in each segment, including `#`/`?`/`%`/`&`/`+`/spaces, is safely escaped), and used it at both call sites:

```javascript
function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}
...
window.open(`/api/download/${encodePath(fullPath)}`, "_blank");
...
const resp = await fetch(`/api/files/${encodePath(fullPath)}`, { method: "DELETE", headers: csrfHeaders() });
```

This matches how FastAPI/Starlette's `{path:path}` converter expects to receive percent-encoded segments and correctly decodes them back to the original filename server-side. Verified directly: the verification script uploads a file named `weird name #1.txt`, then issues `DELETE /api/files/weird%20name%20%231.txt` (the exact string `encodePath()` would produce) against the live route in `app/files/routes.py`, and confirms the file is actually deleted (200, then confirmed gone from the listing) — i.e., the fix round-trips correctly through the real backend, not just in isolation.

I did not change the two spots that already used `encodeURIComponent(fullPath)` as a whole (the pdfjs `?file=` and `viewer.html?path=` cases) — those are correct as written since they're single query-parameter values, not URL path segments, so encoding the `/` characters there is the right behavior, not a bug.

## `getCookie()` / `csrfHeaders()` vs. how the `csrf_token` cookie is actually set (Task 7)

`app/auth/routes.py`'s `/login/verify` sets the CSRF cookie as:

```python
response.set_cookie("csrf_token", csrf_token, max_age=..., httponly=False, secure=True, samesite="strict")
```

`httponly=False` is exactly what makes `getCookie("csrf_token")` (reading via `document.cookie`) viable at all — an `HttpOnly` cookie is invisible to JS. Confirmed via the verification script (`client.cookies.get("csrf_token")` after `/login/verify`, mirroring what `document.cookie` would expose for a non-HttpOnly cookie) that the cookie is set and its value round-trips correctly as the `X-CSRF-Token` header value that `require_csrf` (`app/auth/dependencies.py`) checks against `session["csrf_token"]`. The regex-based `getCookie()` (`(?:^|; )name=([^;]*)`) is standard and correct for parsing `document.cookie`'s semicolon-space-delimited format. No issues found in this logic.

## Manual verification note (per brief Step 5)

The brief's Step 5 asks for interactive browser verification (click through folders, upload, rename, delete, note that PDF/docx preview 404s on the vendored pdfjs path until Task 17 builds the container image). This agent has no browser available; the TestClient-based verification above exercises the identical HTTP contract app.js drives (same URLs, methods, headers, body shapes, and now with the encoding fix, the same string transforms) end-to-end against the real running FastAPI app, which is the strongest verification available without a browser. A human should still do a quick visual pass once the container/dev server is reachable in a browser, per the brief.

## Summary

Implemented `app/static/app.css`, `app/static/index.html` verbatim from the brief, `app/static/app.js` with the `encodePath()` fix described above, and the `GET /app` route in `app/main.py` (additive only, gated on `Depends(get_current_user)`). Full TestClient-based end-to-end session (login → TOTP → list → upload → rename → delete → logout, plus CSRF-rejection and tricky-filename cases) passes 39/39 checks against the real backend. Full existing pytest suite still passes (63/63). One real bug was found and fixed (unencoded filenames in two URL-path-building spots in `app.js`); one pre-existing backend characteristic was flagged but left alone as out of scope (`/logout` doesn't enforce `Depends(require_csrf)`, only `get_current_user`).
