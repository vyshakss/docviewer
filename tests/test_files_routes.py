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
    # Session/pending cookies are set with Secure=True (Task 7), so the client
    # must talk to an https:// base_url or the cookie jar will silently drop
    # them on the next request (see tests/test_auth_routes.py for the same
    # pattern).
    client = TestClient(app, base_url="https://testserver")

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


def test_download_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "files"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_conn_for_tests()
    get_settings().files_root.mkdir(parents=True, exist_ok=True)
    db.init_db(get_settings().db_path)
    (get_settings().files_root / "hello.txt").write_text("hello world")

    from app.main import app
    resp = TestClient(app).get("/api/download/hello.txt")
    assert resp.status_code == 401


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


def test_upload_rejects_absolute_filename_path_traversal(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    # An absolute path in the multipart filename is attacker-controlled and
    # independent of the (correctly sandboxed) `path` query param. Because
    # `Path("/foo/bar") / "/etc/passwd" == Path("/etc/passwd")`, using
    # file.filename unvalidated in `target_dir / file.filename` would let an
    # attacker write anywhere the app process can write, bypassing
    # files_root entirely. This must be rejected outright, not silently
    # reinterpreted as a basename.
    evil_target = tmp_path / "evil_target.txt"
    assert not evil_target.exists()

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": (str(evil_target), b"pwned", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert not evil_target.exists()
    assert list(settings.files_root.iterdir()) == []


def test_upload_rejects_relative_filename_path_traversal(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    evil_target = tmp_path / "evil.txt"
    assert not evil_target.exists()

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": ("../evil.txt", b"pwned", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert not evil_target.exists()
    assert list(settings.files_root.iterdir()) == []


def test_upload_rejects_oversize(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    from app.config import get_settings
    original_max_upload_bytes = get_settings().max_upload_bytes
    get_settings().max_upload_bytes = 10  # patched via cached settings instance
    try:
        resp = client.post(
            "/api/upload",
            params={"path": ""},
            files={"file": ("big.txt", b"x" * 100, "text/plain")},
            headers={"X-CSRF-Token": client.cookies["csrf_token"]},
        )
        assert resp.status_code == 413
    finally:
        get_settings().max_upload_bytes = original_max_upload_bytes


def test_upload_long_filename_does_not_500(tmp_path, monkeypatch):
    # An ordinary-looking 250-character filename is valid input (no path
    # separators, no traversal), but the ".{filename}.part" temp name used
    # during upload can exceed the OS's NAME_MAX (typically 255 bytes on
    # Linux filesystems: 250 + len(".") + len(".part") == 256). This must
    # not surface as an unhandled 500.
    client, settings = _authed_client(tmp_path, monkeypatch)
    long_name = "a" * 250

    resp = client.post(
        "/api/upload",
        params={"path": ""},
        files={"file": (long_name, b"content", "text/plain")},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code != 500
    if resp.status_code == 200:
        assert (settings.files_root / long_name).read_bytes() == b"content"
    else:
        assert resp.status_code == 400
        assert list(settings.files_root.iterdir()) == []


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


def test_rename_rejects_absolute_new_name(tmp_path, monkeypatch):
    # An absolute new_name is attacker-controlled input analogous to the
    # Task 10 upload filename vulnerability: `source.parent / new_name`
    # would resolve to exactly `new_name` if it were allowed through
    # unvalidated, since Path("/a/b") / "/etc/passwd" == Path("/etc/passwd").
    # It must be rejected outright (it contains "/", so the "/" check catches
    # it), not silently reinterpreted as a basename.
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")
    evil_target = tmp_path / "evil_target.txt"
    assert not evil_target.exists()

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": str(evil_target)},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert not evil_target.exists()
    assert (settings.files_root / "old.txt").exists()


def test_rename_rejects_dotdot_new_name(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "sub").mkdir()
    (settings.files_root / "sub" / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "sub/old.txt", "new_name": ".."},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert (settings.files_root / "sub" / "old.txt").exists()


def test_rename_requires_csrf(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "new.txt"},
    )
    assert resp.status_code == 403
    assert (settings.files_root / "old.txt").exists()


def test_move_rejects_traversal_source(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/move",
        json={"path": "../../etc/passwd", "dest": "a.txt"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400


def test_move_rejects_traversal_dest(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "a.txt").write_text("data")

    resp = client.post(
        "/api/move",
        json={"path": "a.txt", "dest": "../../etc/passwd"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert (settings.files_root / "a.txt").exists()


def test_move_requires_csrf(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "a.txt").write_text("data")

    resp = client.post(
        "/api/move",
        json={"path": "a.txt", "dest": "b.txt"},
    )
    assert resp.status_code == 403
    assert (settings.files_root / "a.txt").exists()


def test_delete_rejects_traversal(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)

    # Plain "../../etc/passwd" gets dot-segment-normalized away by the HTTP
    # client itself before the request is even sent (RFC 3986 path
    # normalization), so it never reaches the server as traversal input.
    # Percent-encode the dots so the literal ".." bytes survive client-side
    # normalization and reach resolve_safe_path for a real server-side check.
    resp = client.delete(
        "/api/files/%2e%2e/%2e%2e/etc/passwd",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400


def test_delete_requires_csrf(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "gone.txt").write_text("data")

    resp = client.delete("/api/files/gone.txt")
    assert resp.status_code == 403
    assert (settings.files_root / "gone.txt").exists()


def test_delete_directory_recursive(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "adir").mkdir()
    (settings.files_root / "adir" / "inner.txt").write_text("data")

    resp = client.delete(
        "/api/files/adir",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 200
    assert not (settings.files_root / "adir").exists()


def test_delete_rejects_root_via_empty_path(tmp_path, monkeypatch):
    # path="" (or "." after decoding) resolves to files_root itself via
    # resolve_safe_path — that's legitimate for listing, but must never be a
    # valid delete target: without a guard, shutil.rmtree(files_root) would
    # wipe out the entire file store in a single request.
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "survivor.txt").write_text("data")

    resp = client.delete(
        "/api/files/",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert settings.files_root.exists()
    assert (settings.files_root / "survivor.txt").exists()


def test_delete_rejects_root_via_dot_path(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "survivor.txt").write_text("data")

    resp = client.delete(
        "/api/files/%2e",
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert settings.files_root.exists()
    assert (settings.files_root / "survivor.txt").exists()


def test_rename_rejects_root_as_source(tmp_path, monkeypatch):
    # path="" resolves source to files_root itself. source.parent would then
    # be files_root's *parent* directory, so `source.parent / new_name`
    # would compute a path outside files_root entirely, and source.rename()
    # would relocate the whole file store out of the sandbox.
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "survivor.txt").write_text("data")
    original_location = settings.files_root.resolve()

    resp = client.post(
        "/api/rename",
        json={"path": "", "new_name": "pwned_dir"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert settings.files_root.resolve() == original_location
    assert settings.files_root.exists()
    assert (settings.files_root / "survivor.txt").exists()
    assert not (settings.files_root.parent / "pwned_dir").exists()


def test_rename_rejects_null_byte_in_new_name(tmp_path, monkeypatch):
    # Path("evil\x00name").name == "evil\x00name" (embedded null bytes pass
    # the "differs from basename" check unnoticed), so without defense in
    # depth around the actual os.rename() syscall this raises an uncaught
    # ValueError ("embedded null byte") instead of a clean 4xx.
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "old.txt").write_text("data")

    resp = client.post(
        "/api/rename",
        json={"path": "old.txt", "new_name": "evil\x00name"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert (settings.files_root / "old.txt").exists()


def test_move_rejects_root_as_source(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "survivor.txt").write_text("data")
    original_location = settings.files_root.resolve()

    resp = client.post(
        "/api/move",
        json={"path": "", "dest": "somewhere"},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert settings.files_root.resolve() == original_location
    assert (settings.files_root / "survivor.txt").exists()


def test_move_rejects_root_as_dest(tmp_path, monkeypatch):
    client, settings = _authed_client(tmp_path, monkeypatch)
    (settings.files_root / "a.txt").write_text("data")

    resp = client.post(
        "/api/move",
        json={"path": "a.txt", "dest": ""},
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert resp.status_code == 400
    assert (settings.files_root / "a.txt").exists()
