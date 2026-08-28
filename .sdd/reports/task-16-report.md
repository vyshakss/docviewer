# Task 16 Report — Frontend: text/code/markdown viewer

## Files created

- `app/static/viewer.html` — written verbatim from the brief (Step 1).
- `app/static/viewer.js` — written verbatim from the brief (Step 2).

No other files were created or modified. `app/main.py` was read but not touched — the existing `/static` mount from Task 14 (`app.mount("/static", StaticFiles(directory="app/static"), ...)`) already serves both new files with no new backend route needed, as expected.

## Verification performed

1. **Route/path cross-check (static reading, no execution needed for vendor paths).**
   - Read `app/files/routes.py`: confirmed `GET /api/download/{path:path}` (line 56) is the exact endpoint `viewer.js` fetches (`fetch(\`/api/download/${path}\`)`), and it's guarded by `get_current_user` (session-cookie auth, sent automatically by `fetch` for same-origin requests) with no CSRF requirement (it's a GET/read).
   - Read `app/main.py`: confirmed the `/static` `StaticFiles` mount already covers `app/static/viewer.html` and `app/static/viewer.js` — no route addition required.
   - Read `.sdd/briefs/task-17-brief.md`: confirmed Task 17's Containerfile copies vendored assets to exactly `app/static/vendor/highlight/` (from the highlight.js release zip, which includes `highlight.min.js` and `styles/github-dark.min.css`) and `app/static/vendor/marked/marked.min.js` — matching the paths referenced in `viewer.html` (`/static/vendor/highlight/styles/github-dark.min.css`, `/static/vendor/marked/marked.min.js`, `/static/vendor/highlight/highlight.min.js`) exactly. No path mismatch.
   - Read `app/static/app.js`: confirmed the file browser's `openEntry()` already opens `/static/viewer.html?path=${encodeURIComponent(fullPath)}` for text-like extensions (`.txt`, `.md`, `.py`, `.js`, `.json`, `.c`, `.h`, `.css`, `.html`, `.sh`, `.yaml`, `.yml`), so this new viewer is already wired up to be reachable from Task 15's browser UI with no changes needed on that side.

2. **Logic trace of `viewer.js` (read by eye, no vendored libs available to execute against).**
   - `extensionOf` — lowercases and extracts the substring from the last `.`; returns `""` for no-extension names. Matches `app.js`'s identical helper.
   - `render()`:
     - Parses `path` from `URLSearchParams` — note `URLSearchParams.get` automatically URL-decodes, so a `path` produced by `app.js`'s `encodeURIComponent(fullPath)` (which also escapes `/`) comes back as the original decoded string with real `/` separators intact — consistent with how `fetch(\`/api/download/${path}\`)` needs it (the download route is `{path:path}`, a multi-segment path converter).
     - Missing `path` → sets `content.textContent` to "No file specified." and returns — no crash, no fetch attempted.
     - `fetch` failure path: checks `resp.ok`; on a non-2xx status sets `content.textContent = \`Failed to load file (${resp.status})\`` and returns before touching `resp.text()` — handles 401 (not logged in / session expired), 404 (missing file), 400 (unsafe path) etc. without throwing.
     - `.md` branch calls `marked.parse(text)` into `innerHTML`; other extensions build a `<pre><code>` DOM tree with `code.textContent = text` (safe: uses `textContent`, not `innerHTML`, for the raw file content) and call `hljs.highlightElement(code)` guarded by `if (window.hljs)` so it degrates gracefully (plain unhighlighted text) if the highlight.js script tag failed to load for any reason.
   - No obvious bugs found in the fetch/branch/DOM-manipulation logic.
   - One thing I verified is *not* a bug introduced by me but is inherent to the brief's verbatim code, worth flagging: `fetch(\`/api/download/${path}\`)` interpolates the already-decoded `path` directly without re-encoding it. For ordinary filenames this is fine (the browser encodes the resulting URL string on the way out), but a filename containing characters like `#`, `?`, or `%` could produce a malformed request URL. This mirrors a pattern already accepted elsewhere in the app (Task 17's brief and the existing `app.js` do their own explicit `encodePath` helper for this exact reason in some places but not others), and since the brief specifies this code verbatim as the source of truth for Task 16, I did not deviate from it.
   - Also worth flagging (not changed, per the "use it verbatim" instruction): `content.innerHTML = marked.parse(text)` renders the Markdown file's HTML output unsanitized. This is consistent with a single-user, self-hosted tool previewing one's own files (not attacker-supplied content from other users), and the brief's exact code was supplied as the source of truth, so no sanitizer (e.g. DOMPurify) was added.

3. **TestClient smoke test** (`.venv` Python, via `fastapi.testclient.TestClient`):
   ```
   GET /static/viewer.html -> 200, content-type text/html; charset=utf-8, body byte-for-byte equal to the file on disk
   GET /static/viewer.js   -> 200, content-type text/javascript; charset=utf-8, body byte-for-byte equal to the file on disk
   ```

4. **Regression check**: ran the full existing test suite (`python -m pytest -q`) — **64 passed**, 0 failed. No existing tests were touched; this confirms adding two new static files under `app/static/` did not break anything else in the app (expected, since no Python/backend code changed).

## What was NOT verified (by design, per the task brief and instructions)

- Actual Markdown rendering (`marked.parse`) and syntax highlighting (`hljs.highlightElement`) behavior could not be exercised — `highlight.js` and `marked.js` are not present in this dev environment; they are vendored into `app/static/vendor/` only by Task 17's Containerfile build. This matches the brief's own Step 3 ("Manual verification... deferred to Task 17/18").
- Browser-level end-to-end behavior (opening `viewer.html?path=...` in an actual browser, confirming the page renders correctly) is deferred to Task 17/18 manual verification as the brief specifies.

## Deviations from the brief

None initially. `viewer.html` and `viewer.js` were written character-for-character as specified in `.sdd/briefs/task-16-brief.md` Steps 1 and 2. Step 3 ("Manual verification") was adapted per this task's specific instructions: instead of skipping verification entirely, I performed the static/route cross-checks, logic trace, and TestClient checks described above, all of which are possible without the vendored libraries.

(See "Fix round 1" below for two post-review changes that do deviate from the brief's original verbatim code — both were flagged as real issues by review and fixed as directed by the coordinator.)

## Fix round 1

A task review of the initial submission found two real issues, both of which I had proactively flagged as "Concerns" in my original hand-off but had left unfixed (out of deference to the brief's verbatim code). The coordinator directed both to be fixed. Changes made:

**Issue 1 — functional bug: unencoded `path` in the download fetch URL.**
`viewer.js` was building `fetch(\`/api/download/${path}\`)` directly from the decoded `URLSearchParams` value, with no re-encoding. A filename containing `#`, `?`, or `%` would truncate/split/malform the resulting request URL. This is the same bug class Task 15 fixed in `app.js` via its `encodePath()` helper.

Fix applied to `app/static/viewer.js`:
- Added an `encodePath(path)` function, copied verbatim from `app/static/app.js` (confirmed by reading that file): splits the path on `/`, `encodeURIComponent`s each segment individually, rejoins with unescaped `/`. This preserves real path separators while safely escaping special characters within each segment.
- Changed the fetch call from `fetch(\`/api/download/${path}\`)` to `fetch(\`/api/download/${encodePath(path)}\`)`.
- `extensionOf(path)` (used for the `.md` branch check) still operates on the original, unencoded `path` string — correct, since extension-matching should happen on the real filename, not a URL-encoded form.

**Issue 2 — security hardening: unsanitized Markdown HTML output.**
The `.md` branch called `content.innerHTML = marked.parse(text)` directly. `marked.parse()` does not sanitize its output, so a Markdown file containing raw HTML would be rendered as-is. The app's CSP (`default-src 'self'`, no `unsafe-inline`) blocks the worst-case script-injection chain, but doesn't cover `form-action`/`base-uri`/meta-refresh, leaving a residual phishing/redirect risk from unsanitized markdown-embedded HTML.

Fix applied:
- `app/static/viewer.html`: added `<script src="/static/vendor/dompurify/purify.min.js"></script>` alongside the existing `marked.min.js` and `highlight.min.js` script tags (before `viewer.js`, so `DOMPurify` is defined by the time `viewer.js` runs).
- `app/static/viewer.js`: changed `content.innerHTML = marked.parse(text);` to `content.innerHTML = DOMPurify.sanitize(marked.parse(text));`.

DOMPurify is not yet vendored (Task 17, not yet started, will add it to the container build at `/static/vendor/dompurify/purify.min.js` per the coordinator's message — this is the same situation as the pre-existing, still-unvendored `marked`/`highlight.js` references). The code is correct and ready to work once Task 17 lands that file; it cannot be exercised end-to-end in this dev environment, consistent with the rest of this task's verification constraints.

### Re-verification after fix round 1

1. **File content check** — re-read both files in full after editing; confirmed:
   - `encodePath()` is defined and used at the fetch call site.
   - `extensionOf(path)` still runs against the raw `path`, not the encoded one.
   - `.md` branch now reads `content.innerHTML = DOMPurify.sanitize(marked.parse(text));`.
   - `viewer.html` now includes the `purify.min.js` script tag, ordered before `viewer.js` and after `marked.min.js`/`highlight.min.js`.

2. **TestClient re-check** (`.venv` Python):
   ```
   GET /static/viewer.html -> 200, text/html; charset=utf-8, body byte-for-byte equal to the file on disk
   GET /static/viewer.js   -> 200, text/javascript; charset=utf-8, body byte-for-byte equal to the file on disk
   ```
   Also programmatically confirmed (via string checks against the served body) that: `function encodePath` is present, `fetch(\`/api/download/${encodePath(path)}\`)` is present, `DOMPurify.sanitize(marked.parse(text))` is present, and `vendor/dompurify/purify.min.js` is present in the HTML.

3. **Full regression suite**: `.venv/bin/pytest -v` — **64 passed**, 0 failed, no changes to any existing test. Confirms the two-file frontend edit introduced no backend regressions (expected, since no Python code was touched).

### Updated deviations from the brief

`app/static/viewer.html` and `app/static/viewer.js` now differ from the brief's original verbatim Step 1/Step 2 code in exactly two ways, both requested by the coordinator after review:
1. `viewer.js` gained an `encodePath()` helper and uses it when building the download fetch URL, instead of interpolating `path` raw.
2. `viewer.js`'s markdown branch now wraps `marked.parse(text)` in `DOMPurify.sanitize(...)`, and `viewer.html` gained a `<script src="/static/vendor/dompurify/purify.min.js"></script>` tag to supply it.

Both changes are minimal, additive, and consistent with patterns already established elsewhere in the codebase (`app.js`'s existing `encodePath`), so no further deviation or judgment call was required beyond what the coordinator specified.
