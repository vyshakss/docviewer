# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 17: Containerfile (vendors frontend assets, installs LibreOffice, runs the app)

**Files:**
- Create: `Containerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt`, the full `app/` tree.
- Produces: a buildable OCI image that serves the app on port 8000 as a non-root user.

- [ ] **Step 1: Write `.dockerignore`**

```
tests/
docs/
.env
*.sqlite3
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Write `Containerfile`**

```dockerfile
# --- stage 1: fetch frontend vendor assets ---
FROM node:20-slim AS assets
WORKDIR /assets
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip jq \
    && rm -rf /var/lib/apt/lists/*

# pdf.js prebuilt viewer (full web app, not on npm) — always grab the latest GitHub release asset
RUN curl -sL "$(curl -s https://api.github.com/repos/mozilla/pdf.js/releases/latest \
      | jq -r '.assets[] | select(.name | endswith("dist.zip")) | .browser_download_url')" \
      -o pdfjs.zip \
    && mkdir -p vendor/pdfjs \
    && unzip -q pdfjs.zip -d vendor/pdfjs

# highlight.js prebuilt CDN-style bundle from its latest GitHub release
RUN curl -sL "$(curl -s https://api.github.com/repos/highlightjs/highlight.js/releases/latest \
      | jq -r '.assets[] | select(.name | test("highlight.js-.*\\.zip")) | .browser_download_url' | head -n1)" \
      -o hljs.zip \
    && mkdir -p vendor/highlight \
    && unzip -q hljs.zip -d vendor/highlight

# marked — single-file build, via npm
RUN npm install marked \
    && mkdir -p vendor/marked \
    && cp node_modules/marked/marked.min.js vendor/marked/marked.min.js

# --- stage 2: application image ---
FROM python:3.12-slim
WORKDIR /srv/app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer \
      libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
COPY --from=assets /assets/vendor/pdfjs app/static/vendor/pdfjs
COPY --from=assets /assets/vendor/highlight app/static/vendor/highlight
COPY --from=assets /assets/vendor/marked app/static/vendor/marked

RUN mkdir -p /data/files /data/cache /data/db \
    && chown -R appuser:appuser /srv/app /data

USER appuser
EXPOSE 8000

ENV FILES_ROOT=/data/files \
    DB_PATH=/data/db/docviewer.sqlite3 \
    CACHE_DIR=/data/cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: `SESSION_SECRET` is intentionally not baked into the image — it's supplied at runtime (Task 18's Quadlet unit / `.env`), since it must be unique per deployment and never committed.

- [ ] **Step 3: Manual verification — build and smoke-test the image**

```bash
podman build -t docviewer:local -f Containerfile .
podman run --rm -p 8000:8000 \
  -e SESSION_SECRET="$(openssl rand -hex 32)" \
  -v /tmp/docviewer-files:/data/files \
  docviewer:local
```

In another terminal: `curl http://127.0.0.1:8000/healthz` — expect `{"status":"ok"}`.

Then, inside the running container, provision the one user:

```bash
podman exec -it <container-id> python -m scripts.create_user
```

Visit `http://127.0.0.1:8000/` in a browser, log in with the account just created, confirm the file browser loads, upload a `.pdf` and a `.docx`, and confirm both preview correctly through the vendored PDF.js viewer (the docx one takes a few seconds the first time — that's the LibreOffice conversion running).

