# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 16: Frontend — text/code/markdown viewer

**Files:**
- Create: `app/static/viewer.html`
- Create: `app/static/viewer.js`

**Interfaces:**
- Consumes: `GET /api/download/{path}` (Task 9), vendored `highlight.js` and `marked.js` (populated by Task 17's Containerfile) at `/static/vendor/highlight/` and `/static/vendor/marked/`.

- [ ] **Step 1: Write `app/static/viewer.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer — preview</title>
  <link rel="stylesheet" href="/static/app.css" />
  <link rel="stylesheet" href="/static/vendor/highlight/styles/github-dark.min.css" />
  <style>
    #content { margin: 1rem; }
    pre { white-space: pre-wrap; word-break: break-word; }
  </style>
</head>
<body>
  <div id="content">Loading…</div>
  <script src="/static/vendor/marked/marked.min.js"></script>
  <script src="/static/vendor/highlight/highlight.min.js"></script>
  <script src="/static/viewer.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app/static/viewer.js`**

```javascript
function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

async function render() {
  const params = new URLSearchParams(window.location.search);
  const path = params.get("path");
  const content = document.getElementById("content");

  if (!path) {
    content.textContent = "No file specified.";
    return;
  }

  const resp = await fetch(`/api/download/${path}`);
  if (!resp.ok) {
    content.textContent = `Failed to load file (${resp.status})`;
    return;
  }
  const text = await resp.text();
  const ext = extensionOf(path);

  if (ext === ".md") {
    content.innerHTML = marked.parse(text);
  } else {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = text;
    pre.appendChild(code);
    content.innerHTML = "";
    content.appendChild(pre);
    if (window.hljs) hljs.highlightElement(code);
  }
}

render();
```

- [ ] **Step 3: Manual verification**

Deferred to Task 17/18 manual verification, once `highlight.js`/`marked.js` are vendored by the container build — this task has no automated test since it's pure frontend code with no server logic to unit test.

