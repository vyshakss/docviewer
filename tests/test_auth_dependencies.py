# tests/test_auth_dependencies.py
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _fresh_db(tmp_path):
    from app import db
    db.reset_conn_for_tests()
    db.init_db(tmp_path / "test.sqlite3")


def test_get_current_user_rejects_missing_cookie(tmp_path):
    _fresh_db(tmp_path)
    from app.auth.dependencies import get_current_user

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user=Depends(get_current_user)):
        return {"username": user["username"]}

    client = TestClient(app)
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_get_current_user_accepts_valid_session(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models
    from app.auth.dependencies import get_current_user

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, _csrf = models.create_session(user_id, ttl_seconds=3600)

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user=Depends(get_current_user)):
        return {"username": user["username"]}

    client = TestClient(app)
    client.cookies.set("session_token", raw_token)
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.json() == {"username": "vyshak"}


def test_require_csrf_rejects_missing_header(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models
    from app.auth.dependencies import require_csrf

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, csrf_token = models.create_session(user_id, ttl_seconds=3600)

    app = FastAPI()

    @app.post("/mutate")
    def mutate(_=Depends(require_csrf)):
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("session_token", raw_token)
    resp = client.post("/mutate")
    assert resp.status_code == 403

    resp = client.post("/mutate", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 200
