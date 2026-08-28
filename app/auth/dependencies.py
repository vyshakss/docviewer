# app/auth/dependencies.py
import sqlite3

from fastapi import Depends, HTTPException, Request

from app.auth import models


def get_current_user(request: Request) -> sqlite3.Row:
    raw_token = request.cookies.get("session_token")
    if raw_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = models.get_session(raw_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    user = models.get_user_by_id(session["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    request.state.session = session
    return user


def require_csrf(request: Request, user: sqlite3.Row = Depends(get_current_user)) -> None:
    session = request.state.session
    header_token = request.headers.get("X-CSRF-Token")
    if not header_token or header_token != session["csrf_token"]:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
