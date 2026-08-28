# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 11: Rename, move, delete

**Files:**
- Modify: `app/files/routes.py` (add rename/move/delete routes)
- Modify: `tests/test_files_routes.py` (add tests)

**Interfaces:**
- Produces: `POST /api/rename`, `POST /api/move`, `DELETE /api/files/{path:path}` on `files_router`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_files_routes.py
def test_rename_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "new.txt"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "old.txt").exists()
    assert (settings.files_root / "new.txt").read_text() == "data"


def test_move_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "a.txt").write_text("data")
    (settings.files_root / "sub").mkdir()

    resp = client.post(
        "/api/move",
        json={"path": "a.txt", "dest": "sub/a.txt"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "a.txt").exists()
    assert (settings.files_root / "sub" / "a.txt").read_text() == "data"


def test_delete_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "gone.txt").write_text("data")

    resp = client.delete(
        "/api/files/gone.txt",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "gone.txt").exists()


def test_rename_rejects_traversal_target(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "../../etc/passwd"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v -k "rename or move or delete"`
Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Add routes to `app/files/routes.py`**

```python
# add imports
import shutil
from pydantic import BaseModel


class RenameBody(BaseModel):
    path: str
    new_name: str


class MoveBody(BaseModel):
    path: str
    dest: str


# add after upload_file()
@router.post("/rename")
def rename_file(body: RenameBody, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    if "/" in body.new_name or body.new_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid new name")

    try:
        source = resolve_safe_path(settings.files_root, body.path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # new_name has no "/" (checked above), so it's a single path segment —
    # source.parent / new_name necessarily stays within source's own directory.
    target = source.parent / body.new_name

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    source.rename(target)
    return {"ok": True}


@router.post("/move")
def move_file(body: MoveBody, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    try:
        source = resolve_safe_path(settings.files_root, body.path)
        dest = resolve_safe_path(settings.files_root, body.dest)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if dest.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return {"ok": True}


@router.delete("/files/{path:path}")
def delete_file(path: str, user=Depends(get_current_user), _csrf=Depends(require_csrf)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v`
Expected: PASS (all tests in the file)

