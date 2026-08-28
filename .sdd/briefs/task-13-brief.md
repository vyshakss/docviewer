# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 13: Preview route (`/view/{path}`)

**Files:**
- Create: `app/preview/routes.py`
- Modify: `app/main.py` (mount preview router)
- Test: `tests/test_preview_routes.py`

**Interfaces:**
- Consumes: `app.preview.convert.get_preview_pdf`, `app.files.pathutils.resolve_safe_path`, `app.auth.dependencies.get_current_user`.
- Produces: `app.preview.routes.router`, route `GET /view/{path:path}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preview_routes.py
from unittest.mock import patch
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


def test_view_pdf_streams_directly(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "doc.pdf").write_bytes(b"%PDF-1.4 raw")

    resp = client.get("/view/doc.pdf")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 raw"
    assert resp.headers["content-type"] == "application/pdf"


def test_view_docx_converts_via_cache(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "doc.docx").write_bytes(b"fake docx")

    with patch("app.preview.routes.get_preview_pdf") as mock_convert:
        mock_convert.return_value = None

        def side_effect(source, cache_dir):
            out = cache_dir / "doc.pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"%PDF-1.4 converted")
            return out

        mock_convert.side_effect = side_effect

        resp = client.get("/view/doc.docx")

    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 converted"


def test_view_unsupported_type_returns_415(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "image.png").write_bytes(b"fake png")

    resp = client.get("/view/image.png")
    assert resp.status_code == 415


def test_view_requires_auth(tmp_path, monkeypatch):
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
    resp = TestClient(app).get("/view/doc.pdf")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_preview_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.preview.routes'`

- [ ] **Step 3: Write `app/preview/routes.py`**

```python
# app/preview/routes.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path
from app.preview.convert import ConversionError, get_preview_pdf

router = APIRouter()

_DOC_EXTENSIONS = {".docx", ".doc"}


@router.get("/view/{path:path}")
def view_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = target.suffix.lower()

    if suffix == ".pdf":
        return FileResponse(target, media_type="application/pdf")

    if suffix in _DOC_EXTENSIONS:
        try:
            pdf_path = get_preview_pdf(target, settings.cache_dir)
        except ConversionError:
            raise HTTPException(status_code=502, detail="Conversion failed")
        return FileResponse(pdf_path, media_type="application/pdf")

    raise HTTPException(status_code=415, detail="Unsupported preview type")
```

- [ ] **Step 4: Mount the router in `app/main.py`**

```python
# add near other router imports
from app.preview.routes import router as preview_router

# add after app.include_router(files_router)
app.include_router(preview_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_preview_routes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: All tests across all files PASS.

