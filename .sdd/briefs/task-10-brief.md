# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 10: File upload

**Files:**
- Modify: `app/files/routes.py` (add upload route)
- Modify: `tests/test_files_routes.py` (add upload tests)

**Interfaces:**
- Consumes: `app.auth.dependencies.require_csrf`, `app.files.pathutils.resolve_safe_path`.
- Produces: `POST /api/upload?path=` on the existing `files_router`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_files_routes.py
def test_upload_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("new.txt", b"uploaded content", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert (settings.files_root / "new.txt").read_bytes() == b"uploaded content"


def test_upload_requires_csrf(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("new.txt", b"content", "text/plain")},
    )
    assert resp.status_code == 403


def test_upload_rejects_traversal(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/upload",
        params={"path": "../../etc"},
        files={"file": ("evil.txt", b"content", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400


def test_upload_rejects_oversize(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    from app.config import get_settings
    get_settings().max_upload_bytes = 10  # patched via cached settings instance

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("big.txt", b"x" * 100, "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v -k upload`
Expected: FAIL — `404 Not Found` for `/api/upload` (route doesn't exist yet).

- [ ] **Step 3: Add the upload route to `app/files/routes.py`**

```python
# add imports at top of app/files/routes.py
import os

from fastapi import Query, UploadFile
from app.auth.dependencies import require_csrf

# add after download_file()
@router.post("/upload")
async def upload_file(
    file: UploadFile,
    path: str = Query(""),
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()
    try:
        target_dir = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    dest = target_dir / file.filename
    tmp_dest = target_dir / f".{file.filename}.part"

    total = 0
    with open(tmp_dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                out.close()
                tmp_dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            out.write(chunk)

    os.replace(tmp_dest, dest)
    return {"ok": True, "name": file.filename, "size": total}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v -k upload`
Expected: PASS (4 tests)

