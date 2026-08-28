function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function csrfHeaders() {
  return { "X-CSRF-Token": getCookie("csrf_token") };
}

// Encode a "/"-separated relative path for use as a URL *path* segment
// sequence (as opposed to encodeURIComponent(path), which would also escape
// the "/" separators and mangle the URL). Each segment is escaped on its
// own so filenames containing spaces, "#", "?", "%", "&", "+", etc. still
// produce a URL that resolves to the same path server-side.
function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
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
    window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent("/view/" + encodePath(fullPath))}`, "_blank");
  } else if (TEXT_LIKE.has(ext)) {
    window.open(`/static/viewer.html?path=${encodeURIComponent(fullPath)}`, "_blank");
  } else {
    window.open(`/api/download/${encodePath(fullPath)}`, "_blank");
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

  const resp = await fetch(`/api/files/${encodePath(fullPath)}`, {
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
