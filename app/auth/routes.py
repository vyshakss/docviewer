# app/auth/routes.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import models
from app.auth.dependencies import get_current_user, require_csrf
from app.auth.security import verify_password, verify_totp
from app.config import get_settings
from app.net import client_ip as _client_ip

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class VerifyBody(BaseModel):
    code: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    settings = get_settings()
    ip = _client_ip(request)

    if models.is_locked_out(
        body.username, ip, settings.login_lockout_threshold, settings.login_lockout_window_seconds
    ):
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later")

    user = models.get_user_by_username(body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        models.record_login_attempt(body.username, ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    models.record_login_attempt(body.username, ip, success=True)
    pending_token = models.create_pending_login(user["id"], settings.pending_login_ttl_seconds)

    response.set_cookie(
        "pending_token",
        pending_token,
        max_age=settings.pending_login_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return {"requires_totp": True}


@router.post("/login/verify")
def login_verify(body: VerifyBody, request: Request, response: Response):
    settings = get_settings()
    pending_token = request.cookies.get("pending_token")
    if pending_token is None:
        raise HTTPException(status_code=401, detail="No pending login")

    row = models.verify_and_bump_pending_login(pending_token, max_attempts=5)
    if row is None:
        response.delete_cookie("pending_token")
        raise HTTPException(status_code=401, detail="Pending login expired, please log in again")

    user = models.get_user_by_id(row["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid code")

    ip = _client_ip(request)
    if models.is_locked_out(
        user["username"], ip, settings.login_lockout_threshold, settings.login_lockout_window_seconds
    ):
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later")

    if not verify_totp(user["totp_secret"], body.code):
        models.increment_pending_login_attempts(pending_token)
        models.record_login_attempt(user["username"], ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid code")

    models.delete_pending_login(pending_token)
    session_token, csrf_token = models.create_session(user["id"], settings.session_ttl_seconds)

    response.delete_cookie("pending_token")
    response.set_cookie(
        "session_token",
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return {"ok": True}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    raw_token = request.cookies.get("session_token")
    if raw_token:
        models.delete_session(raw_token)
    response.delete_cookie("session_token")
    response.delete_cookie("csrf_token")
    return {"ok": True}
