# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 15: Frontend — file browser page

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/app.js`
- Create: `app/static/app.css`
- Modify: `app/main.py` (serve `/app`, protect it)

**Interfaces:**
- Consumes: `GET /api/files`, `POST /api/upload`, `POST /api/rename`, `POST /api/move`, `DELETE /api/files/{path}` (Tasks 9-11).
- Produces: a working file browser UI at `/app`.

- [ ] **Step 1: Write `app/static/app.css`**

```css
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
.auth-page { display: flex; align-items: center; justify-content: center; height: 100vh; }
.auth-card { background: #1a1d24; padding: 2rem; border-radius: 8px; width: 320px; }
.auth-card label { display: block; margin-bottom: 1rem; }
.auth-card input { width: 100%; padding: 0.5rem; margin-top: 0.25rem; }
.error { color: #ff6b6b; min-height: 1.2em; }
header { display: flex; align-items: center; gap: 1rem; padding: 1rem; border-bottom: 1px solid #2a2d36; }
#breadcrumbs a { color: #8ab4f8; text-decoration: none; margin-right: 0.25rem; }
table { width: 100%; border-collapse: collapse; margin: 1rem; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #2a2d36; }
tr.entry:hover { background: #1a1d24; cursor: pointer; }
.actions button { margin-right: 0.5rem; }
```

- [ ] **Step 2: Write `app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer</title>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body>
  <header>
    <strong>docviewer</strong>
    <nav id="breadcrumbs"></nav>
    <span style="flex: 1"></span>
    <input type="file" id="upload-input" hidden />
    <button id="upload-button">Upload</button>
    <button id="logout-button">Log out</button>
  </header>
  <table>
    <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead>
    <tbody id="entries"></tbody>
  </table>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `app/static/app.js`**

```javascript
function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function csrfHeaders() {
  return { "X-CSRF-Token": getCookie("csrf_token") };
}

let currentPath = "";

const PREVIEWABLE = new Set([".pdf", ".docx", ".doc"]);
const TEXT_LIKE = new Set([".txt", ".md", ".py", ".js", ".json", ".c", ".h", ".css", ".html", ".sh", ".yaml", ".yml"]);

function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

async function loadEntries(path) {
  const resp = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
  if (resp.status === 401) {
    window.location.href = "/";
    return;
  }
  const data = await resp.json();
  currentPath = path;
  renderBreadcrumbs(path);
  renderEntries(data.entries, path);
}

function renderBreadcrumbs(path) {
  const el = document.getElementById("breadcrumbs");
  el.innerHTML = "";
  const rootLink = document.createElement("a");
  rootLink.textContent = "root";
  rootLink.href = "#";
  rootLink.onclick = () => loadEntries("");
  el.appendChild(rootLink);

  if (!path) return;
  const parts = path.split("/").filter(Boolean);
  let acc = "";
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part;
    el.appendChild(document.createTextNode(" / "));
    const link = document.createElement("a");
    link.textContent = part;
    const target = acc;
    link.onclick = () => loadEntries(target);
    el.appendChild(link);
  }
}

function renderEntries(entries, path) {
  const tbody = document.getElementById("entries");
  tbody.innerHTML = "";
  entries.sort((a, b) => (b.is_dir - a.is_dir) || a.name.localeCompare(b.name));

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.className = "entry";

    const nameCell = document.createElement("td");
    nameCell.textContent = entry.is_dir ? `📁 ${entry.name}` : entry.name;
    nameCell.onclick = () => openEntry(entry, path);
    row.appendChild(nameCell);

    const sizeCell = document.createElement("td");
    sizeCell.textContent = entry.is_dir ? "" : `${entry.size} B`;
    row.appendChild(sizeCell);

    const mtimeCell = document.createElement("td");
    mtimeCell.textContent = new Date(entry.mtime * 1000).toLocaleString();
    row.appendChild(mtimeCell);

    const actionsCell = document.createElement("td");
    actionsCell.className = "actions";
    actionsCell.appendChild(makeButton("Rename", () => renameEntry(entry, path)));
    actionsCell.appendChild(makeButton("Delete", () => deleteEntry(entry, path)));
    row.appendChild(actionsCell);

    tbody.appendChild(row);
  }
}

function makeButton(label, onClick) {
  const button = document.createElement("button");
  button.textContent = label;
  button.onclick = (event) => {
    event.stopPropagation();
    onClick();
  };
  return button;
}

function openEntry(entry, path) {
  const fullPath = path ? `${path}/${entry.name}` : entry.name;
  if (entry.is_dir) {
    loadEntries(fullPath);
    return;
  }
  const ext = extensionOf(entry.name);
  if (PREVIEWABLE.has(ext)) {
    window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent("/view/" + fullPath)}`, "_blank");
  } else if (TEXT_LIKE.has(ext)) {
    window.open(`/static/viewer.html?path=${encodeURIComponent(fullPath)}`, "_blank");
  } else {
    window.open(`/api/download/${fullPath}`, "_blank");
  }
}

async function renameEntry(entry, path) {
  const newName = prompt("New name", entry.name);
  if (!newName || newName === entry.name) return;
  const fullPath = path ? `${path}/${entry.name}` : entry.name;

  const resp = await fetch("/api/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...csrfHeaders() },
    body: JSON.stringify({ path: fullPath, new_name: newName }),
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Rename failed");
}

async function deleteEntry(entry, path) {
  if (!confirm(`Delete ${entry.name}?`)) return;
  const fullPath = path ? `${path}/${entry.name}` : entry.name;

  const resp = await fetch(`/api/files/${fullPath}`, {
    method: "DELETE",
    headers: csrfHeaders(),
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Delete failed");
}

document.getElementById("upload-button").onclick = () => {
  document.getElementById("upload-input").click();
};

document.getElementById("upload-input").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);

  const resp = await fetch(`/api/upload?path=${encodeURIComponent(currentPath)}`, {
    method: "POST",
    headers: csrfHeaders(),
    body: formData,
  });
  if (resp.ok) loadEntries(currentPath);
  else alert((await resp.json()).detail || "Upload failed");
};

document.getElementById("logout-button").onclick = async () => {
  await fetch("/logout", { method: "POST", headers: csrfHeaders() });
  window.location.href = "/";
};

loadEntries("");
```

- [ ] **Step 4: Serve `/app` in `app/main.py`, gated on a valid session**

```python
# add after the "/" route in app/main.py
from fastapi import Depends
from app.auth.dependencies import get_current_user


@app.get("/app")
def app_page(user=Depends(get_current_user)):
    return FileResponse("app/static/index.html")
```

- [ ] **Step 5: Manual verification**

With the server running and a user logged in (Task 14), navigate to `/app`. Confirm: directory listing renders, breadcrumbs update on folder click, upload adds a file to the list, rename/delete work and refresh the list. Note: clicking a PDF/docx will 404 on the vendored viewer path until Task 17 builds the container image — that's expected at this point; verify the `/view/{path}` request itself succeeds by checking the Network tab.

