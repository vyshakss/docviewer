# docviewer — design spec

Date: 2026-08-25

## Purpose

A lightweight, self-hosted web app to view, browse, and manage PDF/docx/text
files that already live on the Fedora server, replacing Nextcloud for this
narrow use case. Nextcloud is too heavy/slow for what's actually needed —
this app does one thing: browse a directory tree, preview files in-browser,
and do basic file management (upload/download/rename/move/delete).

Single user, TOTP-protected, reachable both on the LAN and remotely over the
user's existing domain via Cloudflare Tunnel.

## Non-goals

- No sync engine, no multi-app ecosystem, no calendar/contacts/etc.
- No collaborative/real-time editing — view and manage only.
- No multi-user accounts, groups, or sharing links (out of scope for v1).
- No preview support beyond PDF, docx/doc, and text/code/markdown for v1
  (images, xlsx, pptx explicitly excluded — other file types just download).

## Architecture

One container, running a Python/FastAPI app that serves both a JSON API and
the frontend (server-rendered login page + a small vanilla-JS file
browser/viewer app — no heavy frontend framework).

- **Filesystem is the source of truth.** The app reads/writes directly
  against a bind-mounted host directory (the user's existing file
  collection). No database of file metadata, no indexing/sync step.
- **SQLite** (in a persistent volume) holds: the single user record
  (Argon2id password hash + TOTP secret), sessions, and a login-audit log.
- **Docx→PDF conversion cache**: LibreOffice headless (`soffice
  --convert-to pdf`) run as a subprocess converts docx/doc to PDF on first
  view. The result is cached on disk (also in the persistent volume), keyed
  by source file path + mtime, so repeat views don't reconvert. All
  previewing — native PDFs and converted docx — goes through one PDF.js
  viewer in the browser.
- **Text/code/markdown** are rendered client-side (syntax highlighting +
  markdown rendering) with no server-side conversion step.

```
Browser (PDF.js, vanilla JS)
   |  HTTPS (via Cloudflare Tunnel / LAN)
   v
FastAPI app (single container)
   |-- /login, /api/*  (session + CSRF protected)
   |-- /view/{path}    (streams PDF, or cached converted PDF for docx)
   |
   |-- SQLite (users, sessions, audit log)      [persistent volume]
   |-- docx->pdf conversion cache                [persistent volume]
   |-- LibreOffice headless (subprocess, on demand)
   |
   v
Host directory (bind mount) — the actual files, read/write
```

## Components

- **Auth module**: login (password + TOTP), session issuance/validation,
  logout, lockout tracking.
- **File API**: list directory, get file metadata, upload, download,
  rename, move, delete — all path-scoped and validated against the mounted
  root.
- **Preview/conversion service**: resolves a request for `/view/{path}` to
  either a direct file stream (PDF) or a cached/generated converted PDF
  (docx/doc), invoking LibreOffice headless as needed.
- **Frontend**: login page; file browser (list, breadcrumb navigation,
  upload, rename/move/delete actions); viewer (PDF.js pane for PDF/docx,
  syntax-highlighted pane for text/code/markdown).

## API surface

All `/api/*` and `/view/*` routes require a valid session cookie.

- `GET /api/files?path=` — list a directory's contents (name, size, mtime, type)
- `GET /view/{path}` — stream a PDF, or the cached/converted PDF for docx;
  returns a "processing" status if a large file is still converting
- `GET /api/download/{path}` — raw file download
- `POST /api/upload?path=` — multipart upload, written to a temp file then
  renamed into place (no partial files visible mid-upload)
- `POST /api/rename` — `{path, new_name}`
- `POST /api/move` — `{path, dest}`
- `DELETE /api/files/{path}`
- `POST /login`, `POST /login/verify` (TOTP step), `POST /logout`

Every path parameter is resolved to an absolute path and checked that it
stays within the configured file root before any filesystem operation —
blocks path traversal (`../../etc`, symlink escapes, etc).

## Security

- Password hashed with **Argon2id**.
- Login requires password **and** a TOTP code (6-digit, standard
  authenticator app).
- Sessions: random opaque token, `httponly` + `secure` + `samesite=strict`
  cookie, validated server-side against SQLite (not a signed/stateless
  token, so sessions are individually revocable). Sliding expiry (e.g. 7
  days).
- Failed-login lockout: tracked per IP + username, backs off / locks after
  repeated failures (e.g. 5 attempts → 15 min lock).
- CSRF token required on all state-changing (`POST`/`DELETE`) requests.
- Upload size cap, enforced server-side.
- Runs as a rootless Podman container, non-root user inside the container
  too.
- Container listens on `localhost`/LAN only — never binds a public
  interface directly; remote reachability comes entirely from the existing
  Cloudflare Tunnel, which the user manages outside this project.

## Deployment

- Single container image: Python + FastAPI app + LibreOffice headless
  installed (this is the main contributor to image size — expected, and
  still far lighter than Nextcloud's stack).
- Run via **Podman**, managed as a **systemd Quadlet** unit — auto-start on
  boot, auto-restart on failure, no separate daemon to babysit.
- **Bind mounts**:
  - the user's existing file directory (read-write) — exact host path is a
    deploy-time config value (`FILES_ROOT`), not hardcoded
  - a named volume for the SQLite DB + docx conversion cache (persists
    across container recreation, kept separate from the served files)
- Container binds a local port only; the user adds a new hostname to their
  existing `cloudflared` tunnel config pointing at that port. No new open
  ports on the router/firewall.

## Testing

- `pytest` for the backend: auth flow (login, TOTP, lockout, session
  expiry), path-traversal guards, file operations (upload/rename/move/
  delete), conversion caching (cache hit vs. regenerate on mtime change).
- Manual pass in-browser for the viewer and upload UX (drag-drop, large
  file upload, PDF/docx/text preview rendering) before calling it done —
  this is a real UI, so it gets checked in an actual browser, not just
  asserted by tests.

## Open items for implementation time

- Exact `FILES_ROOT` path to mount — set via environment variable /
  Quadlet mount at deploy time, not decided in this spec.
- Container base image and exact LibreOffice package choice (full suite vs.
  a trimmed `libreoffice-writer`-only install) — resolved during
  implementation to minimize image size while keeping conversion fidelity.
