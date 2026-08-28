function extensionOf(name) {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

// Encode a "/"-separated relative path for use as a URL *path* segment
// sequence (as opposed to encodeURIComponent(path), which would also escape
// the "/" separators and mangle the URL). Each segment is escaped on its
// own so filenames containing spaces, "#", "?", "%", "&", "+", etc. still
// produce a URL that resolves to the same path server-side.
function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

async function render() {
  const params = new URLSearchParams(window.location.search);
  const path = params.get("path");
  const content = document.getElementById("content");

  if (!path) {
    content.textContent = "No file specified.";
    return;
  }

  const resp = await fetch(`/api/download/${encodePath(path)}`);
  if (!resp.ok) {
    content.textContent = `Failed to load file (${resp.status})`;
    return;
  }
  const text = await resp.text();
  const ext = extensionOf(path);

  if (ext === ".md") {
    content.innerHTML = DOMPurify.sanitize(marked.parse(text));
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
