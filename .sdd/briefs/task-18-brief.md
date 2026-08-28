# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 18: Podman Quadlet unit and deployment README

**Files:**
- Create: `docviewer.container`
- Create: `.env.example`
- Create: `README.md`

**Interfaces:**
- Consumes: the image built in Task 17.
- Produces: a systemd-managed, auto-restarting deployment.

- [ ] **Step 1: Write `.env.example`**

```
SESSION_SECRET=changeme-generate-with-openssl-rand-hex-32
```

- [ ] **Step 2: Write `docviewer.container`** (Podman Quadlet unit — place at `~/.config/containers/systemd/docviewer.container` for a rootless user service, or `/etc/containers/systemd/docviewer.container` for a system-wide one)

```ini
[Unit]
Description=docviewer file browser
After=network-online.target

[Container]
Image=localhost/docviewer:local
PublishPort=127.0.0.1:8000:8000
Volume=%h/docviewer-data/files:/data/files:Z
Volume=%h/docviewer-data/state:/data/db:Z
Volume=%h/docviewer-data/state-cache:/data/cache:Z
EnvironmentFile=%h/docviewer-data/docviewer.env

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Replace `%h/docviewer-data/files` with the real path to the existing document collection before first start (this is the `FILES_ROOT` the spec calls a deploy-time decision).

- [ ] **Step 3: Write `README.md`**

```markdown
# docviewer

Lightweight, self-hosted PDF/docx/text viewer and file manager. See
`docs/superpowers/specs/2026-08-25-docviewer-design.md` for the full design.

## Deploy (Fedora Server, rootless Podman)

1. Build the image: `podman build -t docviewer:local -f Containerfile .`
2. Create data directories:
   ```bash
   mkdir -p ~/docviewer-data/state ~/docviewer-data/state-cache
   # point files at your existing document collection, e.g. a bind mount or symlink:
   ln -s /path/to/existing/documents ~/docviewer-data/files
   ```
3. Create `~/docviewer-data/docviewer.env` from `.env.example`, with a real
   `SESSION_SECRET` (`openssl rand -hex 32`).
4. Copy `docviewer.container` to `~/.config/containers/systemd/`.
5. Reload and start:
   ```bash
   systemctl --user daemon-reload
   systemctl --user start docviewer.service
   systemctl --user enable docviewer.service
   ```
6. Provision the one user account:
   ```bash
   podman exec -it systemd-docviewer python -m scripts.create_user
   ```
   Scan the printed QR/URI into an authenticator app (Aegis, Google
   Authenticator, etc).
7. Point your existing `cloudflared` tunnel at `127.0.0.1:8000` under a new
   hostname (e.g. `files.yourdomain.com`), in `~/.cloudflared/config.yml`:
   ```yaml
   ingress:
     - hostname: files.yourdomain.com
       service: http://127.0.0.1:8000
     # ...your other existing ingress rules...
   ```
   Then `systemctl restart cloudflared` (or however your existing tunnel
   service is managed).

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # edit FILES_ROOT/DB_PATH/CACHE_DIR/SESSION_SECRET for local paths
pytest
uvicorn app.main:app --reload
```

Note: local dev without the container won't have `app/static/vendor/`
populated (that's assembled by the Containerfile build) — the login page
and file browser work, but PDF/docx/markdown preview will 404 on vendored
assets until you either build the container or manually populate
`app/static/vendor/` yourself.
```

- [ ] **Step 4: Manual verification**

Follow the README's deploy steps end-to-end on the actual Fedora server against a **copy** of a small test directory first (not the real document collection), confirm the service survives `systemctl --user restart docviewer.service` and comes back up with sessions cleared but files intact, then point `FILES_ROOT` at the real collection and add the Cloudflare Tunnel hostname.

