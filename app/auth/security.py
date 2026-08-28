# app/auth/security.py
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (Argon2Error, InvalidHashError):
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)
