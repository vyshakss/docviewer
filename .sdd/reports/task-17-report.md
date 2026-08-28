# Task 17 Report — Containerfile (vendors frontend assets, installs LibreOffice, runs the app)

## Files created

- `/run/media/vyshak/ssd/docviewer/Containerfile`
- `/run/media/vyshak/ssd/docviewer/.dockerignore`

No other files were modified.

## Summary

Podman (5.8.4) was available, so this was verified with a real `podman build` + `podman run`,
not just a static review. The brief's Containerfile as written does **not** build as-is against
the current state of the internet — three of its assumptions about upstream package/release
layout are stale. All three were found by actually running the build, diagnosed, fixed, and
re-verified. The final image builds cleanly and a full login → upload → PDF preview → DOCX→PDF
(LibreOffice) conversion flow was exercised successfully against the running container.

## `.dockerignore`

Used the brief's exact list, plus two additions:

```
tests/
docs/
.env
*.sqlite3
__pycache__/
*.pyc
.pytest_cache/
.venv/
.sdd/
```

`.venv/` (63 MB, present in this working tree from local dev/test setup) and `.sdd/` (briefs/
reports/progress docs, not part of the runtime image) were added because sending them into the
build context is pure waste — neither is referenced by the Containerfile. This is additive only;
nothing from the brief's list was removed.

## Containerfile — deviations from the brief, with reasoning

All deviations were discovered by actually attempting the build and reading the real failure,
not guessed in advance.

### 1. Added `ca-certificates` to the assets-stage `apt-get install`

The brief's `apt-get install -y --no-install-recommends curl unzip jq` does not pull in
`ca-certificates` (it's a Recommended, not Depends, of `curl` on Debian, and
`--no-install-recommends` was specified). Result: `node:20-slim` has no
`/etc/ssl/certs/ca-certificates.crt`, and every HTTPS `curl` in the assets stage fails immediately
with `curl: (77) error setting certificate file: /etc/ssl/certs/ca-certificates.crt`. Confirmed by
running `curl -v https://api.github.com/...` in an isolated `podman build` step and reproducing
the exact error before fixing it. Fix: added `ca-certificates` explicitly to that apt-get line.

### 2. pdf.js jq filter now excludes `-legacy-dist.zip`

Mozilla's pdf.js releases (currently v6.2.108) now publish **two** assets ending in `dist.zip`:
`pdfjs-<ver>-dist.zip` and `pdfjs-<ver>-legacy-dist.zip`. The brief's filter
(`select(.name | endswith("dist.zip"))`) matches both, so `jq -r` emits two URLs
newline-joined, and `curl -sL "<url1>\n<url2>"` silently fails (curl treats the whole
multi-line string as one malformed argument and downloads nothing, still exiting 0, which is
why the build's `unzip` step then failed on a missing/empty file). Fixed the jq selector to
`select(.name | endswith("dist.zip") and (contains("legacy") | not))` so exactly one URL comes
out regardless of GitHub's asset ordering.

### 3. highlight.js no longer ships a GitHub Release zip; marked no longer ships a minified npm file

- **highlight.js**: the brief's step scrapes the "latest" GitHub release for a
  `highlight.js-*.zip` asset. As of the current latest release (11.12.0), highlight.js's
  GitHub releases carry **zero** attached assets (`"assets": []` in the API response) — the
  project stopped shipping a CDN-style release zip on GitHub. Its prebuilt browser bundle is
  now published as a separate npm package, `@highlightjs/cdn-assets`, which contains exactly the
  same `highlight.min.js` and `styles/*.css` (including `styles/github-dark.min.css`, which
  `viewer.html` references) that used to live in the release zip. Switched the highlight.js
  fetch from the (now nonfunctional) `curl`/GitHub-release path to
  `npm install @highlightjs/cdn-assets`, copying `highlight.min.js` and `styles/` into
  `vendor/highlight/`.
- **marked**: the brief's step does `cp node_modules/marked/marked.min.js …`. The current marked
  npm package (18.0.11) no longer ships a minified single-file build at that path — only
  `lib/marked.esm.js` (ESM, for bundlers) and `lib/marked.umd.js` (a browser-ready UMD bundle,
  unminified, ~44 KB). The UMD build sets `window.marked` with a `.parse` method exactly like the
  old `marked.min.js` did (confirmed by inspecting the UMD wrapper:
  `g["marked"]=f()` and `g.parse=g`), and `viewer.js` calls `marked.parse(text)`, so functionally
  it's a drop-in replacement. Copied `lib/marked.umd.js` to the same runtime path
  (`vendor/marked/marked.min.js`) since `viewer.html` already hard-codes that filename and
  changing frontend HTML is out of scope for this packaging task. Noted in a Containerfile
  comment that the file is not actually minified despite the name.

These three fetches (marked, DOMPurify, `@highlightjs/cdn-assets`) are now combined into one
`npm install` step, matching the pattern the brief already used for `marked` alone.

### 4. DOMPurify addition (as instructed)

Added per the task instructions, not the brief:
- `npm install marked dompurify @highlightjs/cdn-assets` (dompurify added to the existing npm
  install line)
- `cp node_modules/dompurify/dist/purify.min.js vendor/dompurify/purify.min.js`
- `COPY --from=assets /assets/vendor/dompurify app/static/vendor/dompurify` in the final stage

Confirmed `dompurify`'s npm package still ships `dist/purify.min.js` at the expected path (no
staleness issue here, unlike marked/highlight.js). Confirmed at runtime (see verification below)
that `/srv/app/app/static/vendor/dompurify/purify.min.js` exists in the built image and is served
at `/static/vendor/dompurify/purify.min.js`, matching what `app/static/viewer.html` line 17
(`<script src="/static/vendor/dompurify/purify.min.js"></script>`) expects.

### Everything else matches the brief exactly

Both apt-get installs' package lists (`libreoffice-writer`, `libreoffice-core`), the non-root
`appuser` (uid 1000) setup, `COPY requirements.txt .` / `pip install`, `COPY app/ app/` /
`COPY scripts/ scripts/`, the `/data/{files,cache,db}` directories and their ownership, `EXPOSE
8000`, the `FILES_ROOT`/`DB_PATH`/`CACHE_DIR` env vars, and the `uvicorn` CMD are all unchanged
from the brief. `requirements.txt` (`fastapi==0.115.0`, `uvicorn[standard]==0.32.0`,
`pydantic-settings==2.6.1`, `python-multipart==0.0.12`, `argon2-cffi==23.1.0`, `pyotp==2.9.0`)
matches what the Containerfile installs, and `app/main.py`, `app/files/routes.py`,
`app/preview/routes.py`, `app/preview/convert.py` (which shells out to `soffice --headless
--convert-to pdf`), and `scripts/create_user.py` (invoked as `python -m scripts.create_user`, per
`scripts/__init__.py` existing) were all read and cross-checked against the Containerfile's
paths — no other mismatches found.

## Live build

```
$ podman --version
podman version 5.8.4
```

Build was run with `podman build -t docviewer:local -f Containerfile .`. First two attempts
failed for reasons 1–3 above (real errors captured and fixed as described); the third attempt,
after all three fixes were applied, succeeded cleanly:

```
[2/2] STEP 17/17: CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
[2/2] COMMIT docviewer:local
--> c7f4509b0d96
Successfully tagged localhost/docviewer:local
```

```
$ podman images
REPOSITORY                 TAG    IMAGE ID       CREATED        SIZE
localhost/docviewer        local  c7f4509b0d96   ...            628 MB
docker.io/library/python   3.12-slim  72a58063c756  ...          123 MB
docker.io/library/node     20-slim    9da6b4e352d0  ...          205 MB
```

Dangling/intermediate images left over from the two failed attempts were removed with
`podman image prune -f` after the successful build; only the tagged `localhost/docviewer:local`
and the two base images remain.

## Live run + smoke test

Ran with a bind-mounted files directory:

```
$ podman run -d --name docviewer-smoketest -p 127.0.0.1:8000:8000 \
    -e SESSION_SECRET="$(openssl rand -hex 32)" \
    -v /tmp/docviewer-files:/data/files:U,z \
    docviewer:local
```

**Note on the `:U,z` volume flags**: the brief's suggested run command
(`-v /tmp/docviewer-files:/data/files`) does not work unmodified on this host. This machine runs
rootless Podman with SELinux in Enforcing mode. Without `:U`, the bind-mounted host directory is
owned (from the container's user-namespace perspective) by root, not the container's uid-1000
`appuser`, so uploads fail with `PermissionError: [Errno 13] Permission denied`. Without `:z`
(SELinux relabel), even a correctly-uid-mapped directory is blocked by SELinux — `stat` inside
the container shows the right `appuser:appuser` ownership, but plain `ls`/`open` still get
`Permission denied` (an SELinux AVC denial, not a Unix permission issue — `getenforce` confirmed
`Enforcing`). Both problems were confirmed by reproducing and diagnosing each independently, and
both are eliminated by adding `:U,z` to the volume mount. This is a runtime/deployment concern
(the target host's rootless+SELinux configuration), not a Containerfile defect, but it's
important for whoever writes Task 18's Quadlet unit — the volume mount there will need the same
(or equivalent Quadlet `Volume=...:z` / systemd equivalent) treatment, or the host's SELinux
context/subuid mapping needs to be pre-arranged another way.

`/healthz`:

```
$ curl -sS http://127.0.0.1:8000/healthz
{"status":"ok"}
```

User provisioning (piped stdin, since this is non-interactive):

```
$ printf 'smoketestuser\nCorrectHorseBattery123\nCorrectHorseBattery123\n' | \
    podman exec -i docviewer-smoketest python -m scripts.create_user
User created.
Add this account to your authenticator app.
TOTP secret (manual entry): PJPXUXA6WXNWYPU2UF45SN5KB2UIBHO6
Provisioning URI (or generate a QR code from it): otpauth://totp/docviewer:smoketestuser?secret=...&issuer=docviewer
```

Full application flow (scripted via `curl` using the printed TOTP secret to generate a live code
with `pyotp`, since no interactive browser was available in this environment):

- `POST /login` (username+password) → `{"requires_totp":true}`, sets `pending_token` cookie
- `POST /login/verify` (TOTP code) → `{"ok":true}`, sets `session_token` + `csrf_token` cookies
- `POST /api/upload` a real PDF → `{"ok":true,"name":"test.pdf","size":241}`
- `POST /api/upload` a real DOCX (produced with the host's own LibreOffice from a plain-text
  file, to get a genuine `.docx` rather than a hand-rolled fake) →
  `{"ok":true,"name":"test.docx","size":5118}`
- `GET /api/files` → both files listed
- `GET /view/test.pdf` → `status=200 type=application/pdf size=241` (served directly)
- `GET /view/test.docx` (first request, cold — triggers the container's LibreOffice conversion
  via `soffice --headless --convert-to pdf`) → `status=200 type=application/pdf size=17634`,
  took **1.622s**
- `GET /view/test.docx` (second request — cache hit per `app/preview/convert.py`'s
  mtime-keyed cache) → same 200/pdf/17634, took **0.012s**, confirming the conversion cache
  works inside the container

Also checked directly inside the running container:

```
$ podman exec docviewer-smoketest soffice --version
LibreOffice 25.2.3.2 520(Build:2)

$ podman exec docviewer-smoketest id
uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)   # confirms non-root as required

$ podman exec docviewer-smoketest ls app/static/vendor/pdfjs app/static/vendor/highlight \
    app/static/vendor/marked app/static/vendor/dompurify
# pdfjs: LICENSE, build/ (pdf.mjs, pdf.worker.mjs, ...), web/ (viewer.html, viewer.mjs, ...)
# highlight: highlight.min.js, styles/ (incl. github-dark.min.css)
# marked: marked.min.js
# dompurify: purify.min.js
```

`app.js`'s pdf.js integration (`window.open("/static/vendor/pdfjs/web/viewer.html?file=...")`)
was cross-checked against the actual extracted zip structure — `web/viewer.html` exists exactly
where `app.js` expects it. `GET /static/vendor/pdfjs/web/viewer.html` returned `200`.

Cleanup after verification:

```
$ podman stop docviewer-smoketest
$ podman rm -f docviewer-smoketest
$ podman unshare rm -rf /tmp/docviewer-files   # host-side dir owned via container uid mapping
$ podman image prune -f                        # removed 8 dangling images from failed attempts
```

Final `podman images` shows only `localhost/docviewer:local` plus the two base images — no
leftover clutter.

## Things intentionally left alone

- `app/main.py`'s `Content-Security-Policy: default-src 'self'` header was noted while testing —
  `GET /static/vendor/pdfjs/web/viewer.html` returns `200` under it, but a real browser
  rendering the pdf.js viewer page (which loads its own worker/wasm/module scripts) was not
  verified in this environment (no interactive browser tool was available/needed here). This is
  existing Task 16 code, not something in scope for this Containerfile task, so it was left
  untouched; flagging it here only as something worth a real-browser check when this image is
  actually deployed.
- No source files in `app/`, `scripts/`, or `requirements.txt` were modified — this task only
  touched `Containerfile` and `.dockerignore`.

## Verdict

The Containerfile builds successfully with Podman and produces a working image: `/healthz`
responds, the one-time user is provisionable via `python -m scripts.create_user`, login (including
TOTP) works, file upload/listing/download work, direct PDF preview works, and DOCX→PDF preview
works end-to-end through the container's installed LibreOffice, with the conversion cache
functioning. All four vendored frontend asset directories (`pdfjs`, `highlight`, `marked`,
`dompurify`) are present at the exact runtime paths `viewer.html`/`app.js` expect, and the
container runs as the non-root `appuser` (uid 1000) throughout.
