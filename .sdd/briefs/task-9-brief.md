# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 9: File listing and download

**Files:**
- Create: `app/files/routes.py`
- Modify: `app/main.py` (mount files router)
- Test: `tests/test_files_routes.py`

**Interfaces:**
- Consumes: `app.files.pathutils.resolve_safe_path`, `app.auth.dependencies.get_current_user`, `app.config.get_settings`.
- Produces: `app.files.routes.router`, routes `GET /api/files`, `GET /api/download/{path:path}`. (Later tasks add upload/rename/move/delete to this same router.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_routes.py
import pyotp
from fastapi.testclient import TestClient


def _authed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    settings = get_settings()
    settings.files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.db_path)

    from app.auth import models
    from app.auth.security import generate_totp_secret

    secret = generate_totp_secret()
    models.create_user("vyshak", "correct horse battery staple", secret)

    from app.main import app
    client = TestClient(app)

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    return client, settings


def test_list_root_directory(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    (settings.files_root / "notes").mkdir()

    resp = client.get("/api/files", params={"path": ""})
    assert resp.status_code == 200
    names = {entry["name"] for entry in resp.json()["entries"]}
    assert names == {"report.pdf", "notes"}


def test_list_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    get_settings().files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(get_settings().db_path)

    from app.main import app
    resp = TestClient(app).get("/api/files", params={"path": ""})
    assert resp.status_code == 401


def test_list_rejects_traversal(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)
    resp = client.get("/api/files", params={"path": "../../etc"})
    assert resp.status_code == 400


def test_download_file(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "hello.txt").write_text("hello world")

    resp = client.get("/api/download/hello.txt")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_files_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.files.routes'`

- [ ] **Step 3: Write `app/files/routes.py`**

```python
# app/files/routes.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path

router = APIRouter(prefix="/api")


@router.get("/files")
def list_files(path: str = "", user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    for child in target.iterdir():
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return {"entries": entries}


@router.get("/download/{path:path}")
def download_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(target, filename=target.name)
```

- [ ] **Step 4: Mount the router in `app/main.py`**

```python
# add near other router imports in app/main.py
from app.files.routes import router as files_router

# add after app.include_router(auth_router)
app.include_router(files_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_files_routes.py -v`
Expected: PASS (4 tests)

