import os
from pathlib import Path

def test_settings_load_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from app.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.files_root == Path(tmp_path / "files")
    assert settings.db_path == Path(tmp_path / "db.sqlite3")
    assert settings.cache_dir == Path(tmp_path / "cache")
    assert settings.session_ttl_seconds == 604800


def test_healthz(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_docs_endpoints_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_responses_include_no_store_cache_control(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.headers["cache-control"] == "no-store"


def test_oversized_content_length_rejected_before_routing(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from app.config import get_settings
    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    too_big = get_settings().max_upload_bytes + 1
    resp = client.post(
        "/login",
        content=b"{}",
        headers={"Content-Length": str(too_big), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413


def test_normal_small_post_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))

    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    db.init_db(get_settings().db_path)

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/login", json={"username": "nobody", "password": "wrong"})
    # Not 413 — request is small and gets through the pre-routing guard,
    # reaching the actual route logic (which then 401s on bad credentials).
    assert resp.status_code == 401
