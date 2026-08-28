# app/auth/models.py
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.auth.security import hash_password
from app.db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_user(username: str, password: str, totp_secret: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, totp_secret, created_at) VALUES (?, ?, ?, ?)",
        (username, hash_password(password), totp_secret, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_username(username: str) -> sqlite3.Row | None:
    conn = get_conn()
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    conn = get_conn()
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def record_login_attempt(username: str, ip: str, success: bool) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO login_attempts (username, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
        (username, ip, int(success), _now()),
    )
    conn.commit()


def is_locked_out(username: str, ip: str, threshold: int, window_seconds: int) -> bool:
    conn = get_conn()
    cutoff = _future(-window_seconds)
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM login_attempts
        WHERE username = ? AND ip = ? AND success = 0 AND attempted_at >= ?
        """,
        (username, ip, cutoff),
    ).fetchone()
    return row["n"] >= threshold


def create_pending_login(user_id: int, ttl_seconds: int) -> str:
    conn = get_conn()
    raw_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO pending_logins (token_hash, user_id, attempts, expires_at) VALUES (?, ?, 0, ?)",
        (_hash_token(raw_token), user_id, _future(ttl_seconds)),
    )
    conn.commit()
    return raw_token


def verify_and_bump_pending_login(raw_token: str, max_attempts: int) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pending_logins WHERE token_hash = ?", (_hash_token(raw_token),)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now() or row["attempts"] >= max_attempts:
        return None
    return row


def increment_pending_login_attempts(raw_token: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE pending_logins SET attempts = attempts + 1 WHERE token_hash = ?",
        (_hash_token(raw_token),),
    )
    conn.commit()


def delete_pending_login(raw_token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM pending_logins WHERE token_hash = ?", (_hash_token(raw_token),))
    conn.commit()


def create_session(user_id: int, ttl_seconds: int) -> tuple[str, str]:
    conn = get_conn()
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, csrf_token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (_hash_token(raw_token), csrf_token, user_id, _now(), _future(ttl_seconds)),
    )
    conn.commit()
    return raw_token, csrf_token


def get_session(raw_token: str) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?", (_hash_token(raw_token),)
    ).fetchone()
    if row is None or row["expires_at"] < _now():
        return None
    return row


def delete_session(raw_token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(raw_token),))
    conn.commit()
