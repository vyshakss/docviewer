# tests/test_system_routes.py
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
    client = TestClient(app, base_url="https://testserver")

    client.post("/login", json={"username": "vyshak", "password": "correct horse battery staple"})
    code = pyotp.TOTP(secret).now()
    client.post("/login/verify", json={"code": code})

    return client, settings


def test_system_stats_requires_auth(tmp_path, monkeypatch):
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
    resp = TestClient(app).get("/api/system-stats")
    assert resp.status_code == 401


def test_system_stats_returns_expected_shape(tmp_path, monkeypatch):
    client, _settings = _authed_client(tmp_path, monkeypatch)
    resp = client.get("/api/system-stats")
    assert resp.status_code == 200

    body = resp.json()
    assert body["cpu_temp_c"] is None or isinstance(body["cpu_temp_c"], float)
    assert body["uptime_seconds"] is None or isinstance(body["uptime_seconds"], int)
    if body["uptime_seconds"] is not None:
        assert body["uptime_seconds"] >= 0
    assert isinstance(body["disk_total_bytes"], int)
    assert isinstance(body["disk_used_bytes"], int)
    assert 0 <= body["disk_used_bytes"] <= body["disk_total_bytes"]
    assert body["disk_total_bytes"] > 0


def test_system_stats_reports_disk_usage_of_files_root_not_container_root(tmp_path, monkeypatch):
    # shutil.disk_usage("/") inside a container reports the container's own
    # overlay root filesystem, not the host disk backing the bind-mounted
    # files volume — a meaningless number to show as "storage used". Assert
    # it queries the actual mounted data path instead.
    client, settings = _authed_client(tmp_path, monkeypatch)

    import app.system.routes as system_routes
    queried_paths = []
    real_disk_usage = system_routes.shutil.disk_usage

    def spy(path):
        queried_paths.append(path)
        return real_disk_usage(path)

    monkeypatch.setattr(system_routes.shutil, "disk_usage", spy)

    resp = client.get("/api/system-stats")
    assert resp.status_code == 200
    assert queried_paths == [settings.files_root]


def test_read_system_uptime_reads_host_boot_time_not_process_start():
    from app.system.routes import _read_system_uptime_seconds

    with open("/proc/uptime") as f:
        host_uptime = float(f.read().split()[0])

    result = _read_system_uptime_seconds()

    assert result is not None
    # Would be ~0 (process just started) under the old time.monotonic()-based
    # implementation; asserting it's close to /proc/uptime instead proves
    # this reads real host uptime.
    assert abs(result - host_uptime) < 5
