# tests/test_security.py
import pyotp


def test_password_hash_roundtrip():
    from app.auth.security import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_verify_password_with_malformed_hash_returns_false():
    from app.auth.security import verify_password

    assert verify_password("anything", "not-a-valid-argon2-hash") is False


def test_totp_roundtrip():
    from app.auth.security import generate_totp_secret, verify_totp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False


def test_provisioning_uri_contains_issuer_and_username():
    from app.auth.security import generate_totp_secret, provisioning_uri

    secret = generate_totp_secret()
    uri = provisioning_uri(secret, "vyshak")
    assert "docviewer" in uri
    assert "vyshak" in uri
