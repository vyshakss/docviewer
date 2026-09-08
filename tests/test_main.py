# tests/test_main.py
import logging

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
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
    return TestClient(app)


def test_access_log_records_method_path_status_and_real_ip(tmp_path, monkeypatch, caplog):
    client = _client(tmp_path, monkeypatch)

    with caplog.at_level(logging.INFO, logger="docviewer.access"):
        client.get("/healthz", headers={"CF-Connecting-IP": "203.0.113.42"})

    assert "GET" in caplog.text
    assert "/healthz" in caplog.text
    assert "200" in caplog.text
    assert "203.0.113.42" in caplog.text
