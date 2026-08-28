# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 3: Password hashing and TOTP utilities

**Files:**
- Create: `app/auth/__init__.py`
- Create: `app/auth/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Produces: `app.auth.security.hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`, `generate_totp_secret() -> str`, `verify_totp(secret: str, code: str) -> bool`, `provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security.py
import pyotp


def test_password_hash_roundtrip():
    from app.auth.security import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Write `app/auth/security.py`**

```python
# app/auth/security.py
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_security.py -v`
Expected: PASS (3 tests)

