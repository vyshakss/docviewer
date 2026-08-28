def test_init_db_creates_tables(tmp_path):
    from app import db
    db.reset_conn_for_tests()

    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    conn = db.get_conn()

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"users", "sessions", "pending_logins", "login_attempts"} <= tables
