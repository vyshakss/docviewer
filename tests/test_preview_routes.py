from unittest.mock import patch
import pyotp
from fastapi.testclient import TestClient


def _authed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

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
    # base_url must be https:// so the httpx-backed TestClient's cookie jar
    # will store and replay the Secure-flagged session cookies our routes set.
    client = TestClient(app, base_url="https://testserver")
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


def test_view_rejects_traversal(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)

    # Plain "../../etc/passwd" gets dot-segment-normalized away by the HTTP
    # client itself before the request is even sent (RFC 3986 path
    # normalization), so it never reaches the server as traversal input.
    # Percent-encode the dots so the literal ".." bytes survive client-side
    # normalization and reach resolve_safe_path for a real server-side check.
    resp = client.get("/view/%2e%2e/%2e%2e/etc/passwd")
    assert resp.status_code == 400


def test_view_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    get_settings().files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(get_settings().db_path)

    from app.main import app
    resp = TestClient(app).get("/view/doc.pdf")
    assert resp.status_code == 401
