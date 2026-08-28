import time
from datetime import datetime, timedelta, timezone


def _fresh_db(tmp_path):
    from app import db
    db.reset_conn_for_tests()
    db.init_db(tmp_path / "test.sqlite3")


def test_create_and_get_user(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "hunter2-but-better", "SECRET123")
    row = models.get_user_by_username("vyshak")
    assert row is not None
    assert row["id"] == user_id
    assert row["username"] == "vyshak"
    assert row["password_hash"] != "hunter2-but-better"


def test_login_attempt_lockout(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    models.create_user("vyshak", "pw", "SECRET")
    for _ in range(5):
        models.record_login_attempt("vyshak", "1.2.3.4", success=False)

    assert models.is_locked_out("vyshak", "1.2.3.4", threshold=5, window_seconds=900) is True
    assert models.is_locked_out("vyshak", "9.9.9.9", threshold=5, window_seconds=900) is False


def test_pending_login_roundtrip(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=300)

    row = models.verify_and_bump_pending_login(token, max_attempts=5)
    assert row is not None
    assert row["user_id"] == user_id

    models.delete_pending_login(token)
    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_pending_login_expires(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=-1)  # already expired

    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_pending_login_max_attempts(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    token = models.create_pending_login(user_id, ttl_seconds=300)

    for _ in range(5):
        models.increment_pending_login_attempts(token)

    assert models.verify_and_bump_pending_login(token, max_attempts=5) is None


def test_session_roundtrip(tmp_path):
    _fresh_db(tmp_path)
    from app.auth import models

    user_id = models.create_user("vyshak", "pw", "SECRET")
    raw_token, csrf = models.create_session(user_id, ttl_seconds=3600)

    row = models.get_session(raw_token)
    assert row is not None
    assert row["user_id"] == user_id
    assert row["csrf_token"] == csrf

    models.delete_session(raw_token)
    assert models.get_session(raw_token) is None
