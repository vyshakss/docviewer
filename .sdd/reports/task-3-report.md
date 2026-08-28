# Task 3 Report: Password hashing and TOTP utilities

## Summary

Implemented `app/auth/security.py` providing Argon2id password hashing/verification and
pyotp-based TOTP secret generation/verification/provisioning-URI utilities, exactly per the
brief. This is the first file in the new `app/auth` package; only `__init__.py` and
`security.py` were added, per the instruction to not add anything beyond what this brief
specifies (models.py, dependencies.py, routes.py are left for later tasks).

## Files created

- `/run/media/vyshak/ssd/docviewer/app/auth/__init__.py` — new, empty package init file.
- `/run/media/vyshak/ssd/docviewer/app/auth/security.py` — new. Contains:
  - `hash_password(password: str) -> str` — hashes via Argon2 `PasswordHasher`.
  - `verify_password(password: str, hashed: str) -> bool` — verifies, catching
    `VerifyMismatchError` and returning `False` on mismatch.
  - `generate_totp_secret() -> str` — returns `pyotp.random_base32()`.
  - `verify_totp(secret: str, code: str) -> bool` — verifies a TOTP code with
    `valid_window=1`.
  - `provisioning_uri(secret: str, username: str, issuer: str = "docviewer") -> str` —
    returns the `otpauth://` provisioning URI for authenticator apps.

  Content matches the brief's Step 3 code verbatim.

- `/run/media/vyshak/ssd/docviewer/tests/test_security.py` — new. Contains the three tests
  specified in the brief's Step 1 verbatim:
  - `test_password_hash_roundtrip`
  - `test_totp_roundtrip`
  - `test_provisioning_uri_contains_issuer_and_username`

No other files were modified (app/config.py, app/main.py, app/db.py, tests/conftest.py,
tests/test_config.py, tests/test_db.py from Tasks 1-2 were left untouched).

## Test commands and output

### Step 2: Verify test fails before implementation

Command:
```
.venv/bin/pytest tests/test_security.py -v
```

Output (abbreviated):
```
tests/test_security.py::test_password_hash_roundtrip FAILED              [ 33%]
tests/test_security.py::test_totp_roundtrip FAILED                       [ 66%]
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username FAILED [100%]

E       ModuleNotFoundError: No module named 'app.auth'
...
=========================== short test summary info ============================
FAILED tests/test_security.py::test_password_hash_roundtrip - ModuleNotFoundE...
FAILED tests/test_security.py::test_totp_roundtrip - ModuleNotFoundError: No ...
FAILED tests/test_security.py::test_provisioning_uri_contains_issuer_and_username
============================== 3 failed in 0.16s ===============================
```

Matches the brief's expected failure (`ModuleNotFoundError: No module named 'app.auth'`).

### Step 4: Verify test passes after implementation

Command:
```
.venv/bin/pytest tests/test_security.py -v
```

Output:
```
tests/test_security.py::test_password_hash_roundtrip PASSED              [ 33%]
tests/test_security.py::test_totp_roundtrip PASSED                       [ 66%]
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username PASSED [100%]

============================== 3 passed in 0.26s ===============================
```

### Full test suite regression check

Command:
```
.venv/bin/pytest -v
```

Output:
```
tests/test_config.py::test_settings_load_from_env PASSED                 [ 16%]
tests/test_config.py::test_healthz PASSED                                [ 33%]
tests/test_db.py::test_init_db_creates_tables PASSED                     [ 50%]
tests/test_security.py::test_password_hash_roundtrip PASSED              [ 66%]
tests/test_security.py::test_totp_roundtrip PASSED                       [ 83%]
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username PASSED [100%]

======================== 6 passed, 9 warnings in 0.72s =========================
```

All 6 tests pass (3 new from this task, 3 pre-existing from Tasks 1-2). The 9 warnings are
pre-existing and unrelated to this task: a `PydanticDeprecatedSince20` warning from
`app/config.py`'s class-based `Config` (pre-existing from Task 1) and `DeprecationWarning`s
from `asyncio.iscoroutinefunction` inside starlette/fastapi internals. No new warnings were
introduced by this task's code.

## Dependencies

`pyotp` and `argon2-cffi` (imported as `argon2`) were already installed in
`/run/media/vyshak/ssd/docviewer/.venv` (verified via
`.venv/bin/python -c "import pyotp, argon2"` before starting), so no changes to
`requirements.txt` / `requirements-dev.txt` were needed.

## Deviations from the brief

None. All file contents match the brief verbatim, and all steps (write failing test, verify
failure, write implementation, verify pass) were followed in order. (Note: the "Fix round 1"
below required deviating from the brief's exact `verify_password` code, for the reason
described there.)

## Fix round 1

### Finding (from task review)

`verify_password()` only caught `argon2.exceptions.VerifyMismatchError`. If the stored
`hashed` value is malformed/corrupt (not a well-formed Argon2 hash — e.g. an empty string,
or a hash from a different scheme), `PasswordHasher.verify()` raises
`argon2.exceptions.InvalidHashError` instead, which was uncaught. This would cause an
unhandled exception (500) at login instead of failing closed (returning `False`).

### Investigation

Before picking a fix, I checked the actual exception class hierarchy in the installed
`argon2-cffi` version, since the brief's suggested options (`Argon2Error`,
`VerificationError`) needed to be verified against reality rather than assumed:

```
.venv/bin/python -c "
from argon2.exceptions import Argon2Error, VerifyMismatchError, InvalidHashError, VerificationError
print(issubclass(VerifyMismatchError, Argon2Error))   # True
print(issubclass(InvalidHashError, Argon2Error))      # False
print(issubclass(VerificationError, Argon2Error))     # True
"
```

Result: `InvalidHashError` subclasses `ValueError` directly, NOT `Argon2Error`. So catching
only `Argon2Error` (one of the options the finding suggested) would **not** actually catch
the malformed-hash case — it would still raise. I confirmed this by reproducing the exact
failure:

```
.venv/bin/python -c "
from argon2 import PasswordHasher
h = PasswordHasher()
try:
    h.verify('not-a-valid-argon2-hash', 'anything')
except Exception as e:
    print(type(e), type(e).__mro__)
"
# -> <class 'argon2.exceptions.InvalidHashError'> (InvalidHashError, ValueError, Exception, BaseException, object)
```

### Fix applied

In `/run/media/vyshak/ssd/docviewer/app/auth/security.py`, changed the import and except
clause to catch both exception families:

```python
from argon2.exceptions import Argon2Error, InvalidHashError
...
def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (Argon2Error, InvalidHashError):
        return False
```

`Argon2Error` covers `VerifyMismatchError`/`VerificationError` (normal wrong-password case);
`InvalidHashError` is added explicitly since it does not inherit from `Argon2Error` in this
version of the library. Together these make `verify_password` fail closed (return `False`)
for both a wrong password and a malformed/corrupt stored hash.

### Test added

Added to `/run/media/vyshak/ssd/docviewer/tests/test_security.py`:

```python
def test_verify_password_with_malformed_hash_returns_false():
    from app.auth.security import verify_password

    assert verify_password("anything", "not-a-valid-argon2-hash") is False
```

### Test output

`tests/test_security.py -v`:

```
tests/test_security.py::test_password_hash_roundtrip PASSED              [ 25%]
tests/test_security.py::test_verify_password_with_malformed_hash_returns_false PASSED [ 50%]
tests/test_security.py::test_totp_roundtrip PASSED                       [ 75%]
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username PASSED [100%]

============================== 4 passed in 0.25s ===============================
```

Full suite (`.venv/bin/pytest -v`):

```
tests/test_config.py::test_settings_load_from_env PASSED                 [ 14%]
tests/test_config.py::test_healthz PASSED                                [ 28%]
tests/test_db.py::test_init_db_creates_tables PASSED                     [ 42%]
tests/test_security.py::test_password_hash_roundtrip PASSED              [ 57%]
tests/test_security.py::test_verify_password_with_malformed_hash_returns_false PASSED [ 71%]
tests/test_security.py::test_totp_roundtrip PASSED                       [ 85%]
tests/test_security.py::test_provisioning_uri_contains_issuer_and_username PASSED [100%]

======================== 7 passed, 9 warnings in 0.72s =========================
```

7/7 passing, no regressions. Warnings are the same pre-existing ones noted above, unrelated
to this change.

### Files touched in this round

- `/run/media/vyshak/ssd/docviewer/app/auth/security.py` — modified (broadened exception
  handling in `verify_password`).
- `/run/media/vyshak/ssd/docviewer/tests/test_security.py` — modified (added the malformed-hash
  test case).
- `/run/media/vyshak/ssd/docviewer/.sdd/reports/task-3-report.md` — this section appended.
