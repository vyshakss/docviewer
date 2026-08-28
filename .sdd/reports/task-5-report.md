# Task 5 Report: User provisioning CLI script

## Files created

- `/run/media/vyshak/ssd/docviewer/scripts/__init__.py` — new, empty file. Did not previously exist; created so `python -m scripts.create_user` works as a module import (`scripts` needs to be a package).
- `/run/media/vyshak/ssd/docviewer/scripts/create_user.py` — new file, copied verbatim from the brief (Step 1). No deviations from the brief's exact code.

No other files were modified. Tasks 1-4 (`app/config.py`, `app/db.py`, `app/auth/security.py`, `app/auth/models.py`) were consumed as-is, matching the interfaces the brief expected (`init_db`, `get_conn`, `create_user`, `get_user_by_username`, `generate_totp_secret`, `provisioning_uri`, `get_settings`).

## Deviations from the brief

None in the script content. The only addition beyond the brief's literal file list is `scripts/__init__.py`, which the brief's own "Manually verify" instructions implicitly require (`python -m scripts.create_user` needs `scripts` to be an importable package) but didn't call out as a file to create. This is noted explicitly in the task instructions given to me, so it's expected, not a deviation in intent.

## Manual verification

All commands run from `/run/media/vyshak/ssd/docviewer` using `.venv/bin/python`. Test environment: `FILES_ROOT=/tmp/docviewer-test/files`, `DB_PATH=/tmp/docviewer-test/db.sqlite3`, `CACHE_DIR=/tmp/docviewer-test/cache`, `SESSION_SECRET=test-secret`, exported into the shell (not prefixed on the single command) so they apply to the whole `printf | python` pipeline.

Note: `getpass` emits a `GetPassWarning` to stderr when stdin isn't a real TTY and falls back to reading plaintext from stdin — expected here since this is a non-interactive agent piping input.

### 1. Happy path: create `testuser`

```
$ export FILES_ROOT=/tmp/docviewer-test/files DB_PATH=/tmp/docviewer-test/db.sqlite3 CACHE_DIR=/tmp/docviewer-test/cache SESSION_SECRET=test-secret
$ printf 'testuser\ntestpassword123\ntestpassword123\n' | .venv/bin/python -m scripts.create_user
Username: /usr/lib64/python3.14/getpass.py:99: GetPassWarning: Can not control echo on the terminal.
  passwd = fallback_getpass(prompt, stream)
Warning: Password input may be echoed.
Password: 
Warning: Password input may be echoed.
Confirm password: 

User created.
Add this account to your authenticator app.

TOTP secret (manual entry): KGMWCVLDEWVH53NP2OSOHLELAYARHEEX
Provisioning URI (or generate a QR code from it): otpauth://totp/docviewer:testuser?secret=KGMWCVLDEWVH53NP2OSOHLELAYARHEEX&issuer=docviewer

$ echo "EXIT CODE: $?"
EXIT CODE: 0
```

Confirms: prompts for username/password, prints a TOTP secret and a well-formed `otpauth://` URI, exits 0.

### 2. Verify the row landed in the DB (as the brief's verification snippet suggests)

```
$ .venv/bin/python -c "
from app.config import get_settings
from app.db import init_db, get_conn
from app.auth import models
init_db(get_settings().db_path)
row = models.get_user_by_username('testuser')
print(dict(row))
"
{'id': 1, 'username': 'testuser', 'password_hash': '$argon2id$v=19$m=65536,t=3,p=4$IJ8FvfPe+N7MoRtajVBbhA$YlgJSB4PohG9qybp+bd+YTBhprKiOfoREc1eV/rDcno', 'totp_secret': 'KGMWCVLDEWVH53NP2OSOHLELAYARHEEX', 'created_at': '2026-08-25T09:25:58.291449+00:00'}
```

Confirms: row exists, `password_hash` is an Argon2id hash (non-plaintext), `totp_secret` matches what was printed.

### 3. Failure path (a): duplicate username

```
$ printf 'testuser\nanotherpassword123\nanotherpassword123\n' | .venv/bin/python -m scripts.create_user
Username: User 'testuser' already exists.
$ echo "EXIT CODE: $?"
EXIT CODE: 1
```

Confirms: clear "already exists" message on stderr, exit code 1, no password prompt reached (fails fast before getpass).

### 4. Failure path (b): password under 12 characters

```
$ printf 'shortpwuser\nshortpw1\nshortpw1\n' | .venv/bin/python -m scripts.create_user
Username: /usr/lib64/python3.14/getpass.py:99: GetPassWarning: Can not control echo on the terminal.
  passwd = fallback_getpass(prompt, stream)
Warning: Password input may be echoed.
Password: 
Warning: Password input may be echoed.
Confirm password: 
Password must be at least 12 characters.
$ echo "EXIT CODE: $?"
EXIT CODE: 1
```

Confirms: "at least 12 characters" message, exit code 1.

### 5. Failure path (c): mismatched password confirmation

```
$ printf 'mismatchuser\npassword12345\ndifferentpassword12345\n' | .venv/bin/python -m scripts.create_user
Username: /usr/lib64/python3.14/getpass.py:99: GetPassWarning: Can not control echo on the terminal.
  passwd = fallback_getpass(prompt, stream)
Warning: Password input may be echoed.
Password: 
Warning: Password input may be echoed.
Confirm password: 
Passwords did not match.
$ echo "EXIT CODE: $?"
EXIT CODE: 1
```

Confirms: "Passwords did not match." message, exit code 1.

### 6. No partial writes from rejected attempts

```
$ .venv/bin/python -c "
from app.config import get_settings
from app.db import init_db, get_conn
init_db(get_settings().db_path)
rows = get_conn().execute('SELECT id, username FROM users').fetchall()
for r in rows:
    print(dict(r))
"
{'id': 1, 'username': 'testuser'}
```

Confirms: `shortpwuser` and `mismatchuser` (from the rejected attempts) never landed in the DB — only `testuser` exists. Rejections happen before `models.create_user()` is called, so this is expected by construction, and the DB query confirms it in practice.

### 7. Regression check: existing test suite still passes

```
$ .venv/bin/python -m pytest -q
...
13 passed, 9 warnings in 1.13s
```

No existing tests were affected by adding `scripts/__init__.py` and `scripts/create_user.py`.

### Cleanup

Removed the ephemeral test environment (`/tmp/docviewer-test/`) and stray `scripts/__pycache__` after verification; only the two source files remain under `scripts/`.

## Summary

`scripts/create_user.py` and `scripts/__init__.py` were created exactly per the brief. Verified via piped-stdin non-interactive runs: happy path creates a user with a correct Argon2id-hashed password and a valid `otpauth://` provisioning URI; duplicate-username, short-password, and password-mismatch cases are all correctly rejected with clear stderr messages and exit code 1, with no partial DB writes. Existing test suite (13 tests) remains green.
