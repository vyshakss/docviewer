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
let currentEntries = [];
let searchQuery = "";

const PREVIEWABLE = new Set([".pdf", ".docx", ".doc"]);
const TEXT_LIKE = new Set([".txt", ".md", ".py", ".js", ".json", ".c", ".h", ".css", ".html", ".sh", ".yaml", ".yml"]);

const ICONS = {
  pdf: "📕", doc: "📘", docx: "📘",
  txt: "📝", md: "📝", py: "📝", js: "📝", json: "📝", c: "📝", h: "📝", css: "📝", html: "📝", sh: "📝", yaml: "📝", yml: "📝",
  jpg: "🖼️", jpeg: "🖼️", png: "🖼️", gif: "🖼️", svg: "🖼️", webp: "🖼️",
  zip: "🗜️", tar: "🗜️", gz: "🗜️", "7z": "🗜️", rar: "🗜️",
};

function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

function iconFor(entry) {
  if (entry.is_dir) return "📁";
  return ICONS[extensionOf(entry.name).slice(1)] || "📄";
}

function formatFileSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

const contextMenu = document.getElementById("context-menu");
let contextMenuRow = null;

async function loadEntries(path, highlightName) {
  const resp = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
  if (resp.status === 401) {
    window.location.href = "/";
    return;
  }
  const data = await resp.json();
  currentPath = path;
  currentEntries = data.entries;
  renderBreadcrumbs(path);
  renderFilteredEntries(highlightName);
}

function navigateTo(path) {
  searchQuery = "";
  document.getElementById("search-input").value = "";
  loadEntries(path);
}

function renderFilteredEntries(highlightName) {
  const query = searchQuery.trim().toLowerCase();
  const filtered = query
    ? currentEntries.filter((entry) => entry.name.toLowerCase().includes(query))
    : currentEntries;
  renderEntries(filtered, currentPath, highlightName);
}

function renderBreadcrumbs(path) {
  const el = document.getElementById("breadcrumbs");
  el.innerHTML = "";
  const rootLink = document.createElement("a");
  rootLink.textContent = "root";
  rootLink.href = "#";
  rootLink.onclick = () => navigateTo("");
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
    link.onclick = () => navigateTo(target);
    el.appendChild(link);
  }
}

function renderEntries(entries, path, highlightName) {
  closeContextMenu();
  const tbody = document.getElementById("entries");
  tbody.innerHTML = "";
  entries.sort((a, b) => (b.is_dir - a.is_dir) || a.name.localeCompare(b.name));

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.className = "entry";
    if (highlightName && entry.name === highlightName) {
      row.classList.add("just-uploaded");
      row.addEventListener("animationend", () => row.classList.remove("just-uploaded"), { once: true });
    }

    const nameCell = document.createElement("td");
    const icon = document.createElement("span");
    icon.className = "entry-icon";
    icon.textContent = iconFor(entry);
    nameCell.appendChild(icon);
    nameCell.appendChild(document.createTextNode(entry.name));
    nameCell.onclick = () => openEntry(entry, path);
    row.appendChild(nameCell);

    const sizeCell = document.createElement("td");
    sizeCell.textContent = entry.is_dir ? "" : formatFileSize(entry.size);
    row.appendChild(sizeCell);

    const mtimeCell = document.createElement("td");
    mtimeCell.textContent = new Date(entry.mtime * 1000).toLocaleString();
    row.appendChild(mtimeCell);

    const menuCell = document.createElement("td");
    menuCell.className = "menu-col";
    const menuButton = document.createElement("button");
    menuButton.type = "button";
    menuButton.className = "row-menu-btn";
    menuButton.textContent = "⋮";
    menuButton.setAttribute("aria-label", `More actions for ${entry.name}`);
    menuButton.onclick = (event) => {
      event.stopPropagation();
      const rect = menuButton.getBoundingClientRect();
      openContextMenu(rect.left, rect.bottom, row, entry, path);
    };
    menuCell.appendChild(menuButton);
    row.appendChild(menuCell);

    row.oncontextmenu = (event) => {
      event.preventDefault();
      openContextMenu(event.clientX, event.clientY, row, entry, path);
    };

    tbody.appendChild(row);
  }
}

function openContextMenu(x, y, row, entry, path) {
  closeContextMenu();

  contextMenu.querySelector('[data-action="rename"]').onclick = () => {
    closeContextMenu();
    renameEntry(entry, path);
  };
  contextMenu.querySelector('[data-action="delete"]').onclick = () => {
    closeContextMenu();
    deleteEntry(entry, path);
  };

  contextMenu.hidden = false;
  const maxX = window.innerWidth - contextMenu.offsetWidth - 8;
  const maxY = window.innerHeight - contextMenu.offsetHeight - 8;
  contextMenu.style.left = `${Math.max(8, Math.min(x, maxX))}px`;
  contextMenu.style.top = `${Math.max(8, Math.min(y, maxY))}px`;

  row.classList.add("menu-open");
  contextMenuRow = row;

  document.addEventListener("click", handleContextMenuOutsideClick);
  document.addEventListener("keydown", handleContextMenuKeydown);
}

function closeContextMenu() {
  contextMenu.hidden = true;
  if (contextMenuRow) contextMenuRow.classList.remove("menu-open");
  contextMenuRow = null;
  document.removeEventListener("click", handleContextMenuOutsideClick);
  document.removeEventListener("keydown", handleContextMenuKeydown);
}

function handleContextMenuOutsideClick(event) {
  if (!contextMenu.contains(event.target)) closeContextMenu();
}

function handleContextMenuKeydown(event) {
  if (event.key === "Escape") closeContextMenu();
}

function openEntry(entry, path) {
  const fullPath = path ? `${path}/${entry.name}` : entry.name;
  if (entry.is_dir) {
    navigateTo(fullPath);
    return;
  }
  const ext = extensionOf(entry.name);
  if (PREVIEWABLE.has(ext)) {
    // pdf.js's viewer does `new URL(file).href` with no base, which throws
    // for a relative path and falls back to blindly re-encodeURIComponent'ing
    // the string — corrupting any already-percent-encoded characters (e.g.
    // spaces) in the path. Passing an absolute URL avoids that fallback.
    const fileUrl = new URL("/view/" + encodePath(fullPath), window.location.origin).href;
    window.open(`/static/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent(fileUrl)}`, "_blank");
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

document.getElementById("search-input").oninput = (event) => {
  searchQuery = event.target.value;
  renderFilteredEntries();
};

document.getElementById("new-folder-button").onclick = async () => {
  const name = prompt("Folder name");
  if (!name) return;

  const resp = await fetch("/api/mkdir", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...csrfHeaders() },
    body: JSON.stringify({ path: currentPath, name }),
  });
  if (resp.ok) loadEntries(currentPath, name);
  else alert((await resp.json()).detail || "Failed to create folder");
};

document.getElementById("upload-button").onclick = () => {
  document.getElementById("upload-input").click();
};

document.getElementById("upload-folder-button").onclick = () => {
  document.getElementById("upload-folder-input").click();
};

const uploadProgress = document.getElementById("upload-progress");
const uploadProgressBar = document.getElementById("upload-progress-bar");
const uploadProgressLabel = document.getElementById("upload-progress-label");

function setUploadProgress(fraction, label) {
  uploadProgressBar.style.width = `${Math.round(fraction * 100)}%`;
  uploadProgressLabel.textContent = label;
}

function joinPath(base, rel) {
  if (!base) return rel;
  if (!rel) return base;
  return `${base}/${rel}`;
}

function uploadFile(file, path, name, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload?path=${encodeURIComponent(path)}`);
    const csrf = csrfHeaders();
    for (const [key, value] of Object.entries(csrf)) xhr.setRequestHeader(key, value);

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      onProgress(event.loaded);
    };

    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON error body */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body.detail || "Upload failed"));
    };
    xhr.onerror = () => reject(new Error("Upload failed"));

    const formData = new FormData();
    // Explicit filename: some browsers (Safari) set File.name to a full
    // relative path for directory-picked files instead of just the
    // basename, which the server rejects outright.
    formData.append("file", file, name);
    xhr.send(formData);
  });
}

// --- folder upload ---------------------------------------------------------
// A folder upload is expressed entirely in terms of the existing single-file
// endpoints: /api/mkdir creates one path segment at a time (shallowest first),
// then each file is uploaded with its relative subdirectory in `path`. Nothing
// server-side has to interpret a client-supplied multi-segment path, so the
// filename sanitization in app/files/routes.py stays exactly as strict as it
// is for a single upload.

// Files picked via <input webkitdirectory> carry their subpath in
// webkitRelativePath ("folder/sub/a.txt"); everything before the last "/" is
// the directory that file belongs in, and everything after is the real
// filename. Safari sets File.name to the *whole* relative path for these
// (Chrome/Firefox use just the basename), so `name` must always be derived
// from webkitRelativePath here rather than trusted from file.name.
function entriesFromFileList(fileList) {
  return Array.from(fileList).map((file) => {
    const rel = file.webkitRelativePath || "";
    const cut = rel.lastIndexOf("/");
    return {
      file,
      relDir: cut === -1 ? "" : rel.slice(0, cut),
      name: cut === -1 ? file.name : rel.slice(cut + 1),
    };
  });
}

// readEntries() returns at most ~100 entries per call and signals completion
// with an empty batch, so it has to be called in a loop — a single call
// silently truncates any directory larger than one batch.
function readAllEntries(reader) {
  return new Promise((resolve, reject) => {
    const collected = [];
    const readBatch = () => reader.readEntries((batch) => {
      if (!batch.length) resolve(collected);
      else { collected.push(...batch); readBatch(); }
    }, reject);
    readBatch();
  });
}

async function walkEntry(entry, parentDir, out) {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    // entry.name is the FileSystemEntry's own name, reliable across browsers
    // unlike File.name (which Safari sets to the full relative path here).
    out.push({ file, relDir: parentDir, name: entry.name });
    return;
  }
  const dir = joinPath(parentDir, entry.name);
  for (const child of await readAllEntries(entry.createReader())) {
    await walkEntry(child, dir, out);
  }
}

// Everything this reads off the DataTransfer must be read synchronously: the
// object is neutered once the drop handler yields, so the entries and the flat
// file list are both captured before the first await.
async function entriesFromDataTransfer(dataTransfer) {
  const roots = Array.from(dataTransfer.items || [])
    .filter((item) => item.kind === "file")
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean);
  const flat = Array.from(dataTransfer.files || []).map((file) => ({ file, relDir: "", name: file.name }));
  if (!roots.length) return flat;

  const out = [];
  for (const root of roots) await walkEntry(root, "", out);
  return out;
}

// Every directory level that has to exist, shallowest first, so each mkdir
// call finds its parent already there (mkdir is deliberately non-recursive).
function directoriesFor(entries) {
  const dirs = new Set();
  for (const { relDir } of entries) {
    if (!relDir) continue;
    const parts = relDir.split("/");
    for (let i = 1; i <= parts.length; i += 1) dirs.add(parts.slice(0, i).join("/"));
  }
  return Array.from(dirs).sort(
    (a, b) => a.split("/").length - b.split("/").length || a.localeCompare(b)
  );
}

async function createDirectory(basePath, relDir) {
  const parts = relDir.split("/");
  const name = parts.pop();
  const resp = await fetch("/api/mkdir", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...csrfHeaders() },
    body: JSON.stringify({ path: joinPath(basePath, parts.join("/")), name }),
  });
  if (resp.ok || resp.status === 409) return;  // 409: already exists, reuse it
  let detail = "Failed to create folder";
  try { detail = (await resp.json()).detail || detail; } catch { /* non-JSON error body */ }
  throw new Error(detail);
}

// Failures are collected rather than thrown: aborting a several-hundred-file
// tree on one bad file would leave it half-copied with no obvious way to
// resume, so every file gets its turn and the summary comes at the end.
async function uploadEntries(entries, basePath) {
  const totalBytes = entries.reduce((sum, entry) => sum + entry.file.size, 0);
  const failures = [];
  const failedDirs = new Set();
  let doneBytes = 0;
  let done = 0;

  setUploadProgress(0, `0/${entries.length}`);
  uploadProgress.hidden = false;

  try {
    for (const relDir of directoriesFor(entries)) {
      try {
        await createDirectory(basePath, relDir);
      } catch (err) {
        failedDirs.add(relDir);
        failures.push(`${relDir}/: ${err.message}`);
      }
    }

    for (const { file, relDir, name } of entries) {
      const label = joinPath(relDir, name);
      if (relDir && failedDirs.has(relDir)) {
        // Its directory never got created, so the upload could only 404.
        failures.push(`${label}: skipped, folder missing`);
      } else {
        try {
          await uploadFile(file, joinPath(basePath, relDir), name, (loaded) => {
            if (totalBytes) {
              setUploadProgress((doneBytes + loaded) / totalBytes, `${done}/${entries.length}`);
            }
          });
        } catch (err) {
          failures.push(`${label}: ${err.message}`);
        }
      }
      doneBytes += file.size;
      done += 1;
      setUploadProgress(totalBytes ? doneBytes / totalBytes : 1, `${done}/${entries.length}`);
    }
  } finally {
    uploadProgress.hidden = true;
    setUploadProgress(0, "");
  }

  return failures;
}

async function runUpload(entries) {
  if (!entries.length) return;
  const basePath = currentPath;
  const failures = await uploadEntries(entries, basePath);

  // Highlight the top-level thing that arrived: the folder for a tree, the
  // file itself for a plain upload.
  const first = entries[0];
  const highlight = first.relDir ? first.relDir.split("/")[0] : first.name;
  await loadEntries(basePath, highlight);

  if (failures.length) {
    const shown = failures.slice(0, 10).join("\n");
    const rest = failures.length > 10 ? `\n…and ${failures.length - 10} more` : "";
    alert(`${failures.length} of ${entries.length} item(s) failed:\n\n${shown}${rest}`);
  }
}

document.getElementById("upload-input").onchange = async (event) => {
  const entries = Array.from(event.target.files).map((file) => ({ file, relDir: "", name: file.name }));
  event.target.value = "";
  await runUpload(entries);
};

document.getElementById("upload-folder-input").onchange = async (event) => {
  const entries = entriesFromFileList(event.target.files);
  event.target.value = "";
  await runUpload(entries);
};

// --- drag and drop ---------------------------------------------------------
// dragenter/dragleave fire for every element the pointer crosses, so the
// highlight is refcounted rather than toggled.
let dragDepth = 0;

function dragCarriesFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

document.addEventListener("dragenter", (event) => {
  if (!dragCarriesFiles(event)) return;
  dragDepth += 1;
  document.body.classList.add("drag-active");
});

document.addEventListener("dragover", (event) => {
  if (!dragCarriesFiles(event)) return;
  event.preventDefault();  // without this the browser opens the file instead
  event.dataTransfer.dropEffect = "copy";
});

document.addEventListener("dragleave", (event) => {
  if (!dragCarriesFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) document.body.classList.remove("drag-active");
});

document.addEventListener("drop", async (event) => {
  if (!dragCarriesFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("drag-active");

  let entries;
  try {
    entries = await entriesFromDataTransfer(event.dataTransfer);
  } catch {
    alert("Could not read the dropped folder");
    return;
  }
  await runUpload(entries);
});

document.getElementById("logout-button").onclick = async () => {
  await fetch("/logout", { method: "POST", headers: csrfHeaders() });
  window.location.href = "/";
};

function currentTheme() {
  return document.documentElement.getAttribute("data-theme")
    || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("theme-toggle").textContent = theme === "light" ? "🌙" : "☀️";
}

function initTheme() {
  const saved = localStorage.getItem("theme");
  applyTheme(saved || currentTheme());
}

document.getElementById("theme-toggle").onclick = () => {
  const next = currentTheme() === "light" ? "dark" : "light";
  localStorage.setItem("theme", next);
  applyTheme(next);
};

function tickClock() {
  document.getElementById("stat-time").textContent = new Date().toLocaleTimeString();
}

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatBytes(bytes) {
  const gb = bytes / (1024 ** 3);
  return `${gb.toFixed(1)} GB`;
}

async function loadSystemStats() {
  const resp = await fetch("/api/system-stats");
  if (!resp.ok) return;
  const stats = await resp.json();

  document.getElementById("stat-cpu-temp").textContent =
    stats.cpu_temp_c === null ? "N/A" : `${stats.cpu_temp_c.toFixed(1)}°C`;
  document.getElementById("stat-uptime").textContent =
    stats.uptime_seconds === null ? "N/A" : formatUptime(stats.uptime_seconds);
  document.getElementById("stat-storage").textContent =
    `${formatBytes(stats.disk_used_bytes)} / ${formatBytes(stats.disk_total_bytes)}`;
}

initTheme();
tickClock();
setInterval(tickClock, 1000);
loadSystemStats();
setInterval(loadSystemStats, 30000);

loadEntries("");
