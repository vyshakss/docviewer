# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 5: User provisioning CLI script

**Files:**
- Create: `scripts/create_user.py`

**Interfaces:**
- Consumes: `app.db.init_db`, `app.auth.models.create_user`, `app.auth.models.get_user_by_username`, `app.auth.security.generate_totp_secret`, `app.auth.security.provisioning_uri`, `app.config.get_settings`.
- Produces: a runnable CLI, no importable interface consumed by later tasks.

- [ ] **Step 1: Write the script**

```python
# scripts/create_user.py
"""Provision the single docviewer user. Run once, interactively, on the server.

Usage: python -m scripts.create_user
"""
import getpass
import sys

from app.auth import models
from app.auth.security import generate_totp_secret, provisioning_uri
from app.config import get_settings
from app.db import init_db


def main() -> None:
    settings = get_settings()
    init_db(settings.db_path)

    username = input("Username: ").strip()
    if models.get_user_by_username(username) is not None:
        print(f"User '{username}' already exists.", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(1)

    secret = generate_totp_secret()
    models.create_user(username, password, secret)

    uri = provisioning_uri(secret, username)
    print("\nUser created.")
    print("Add this account to your authenticator app.")
    print(f"\nTOTP secret (manual entry): {secret}")
    print(f"Provisioning URI (or generate a QR code from it): {uri}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manually verify**

Run (with env vars set, e.g. from `.env`): `python -m scripts.create_user`

Expected: prompts for username/password, prints a TOTP secret and `otpauth://` URI. Confirm with:

```bash
python -c "
from app.config import get_settings
from app.db import init_db, get_conn
from app.auth import models
init_db(get_settings().db_path)
print(models.get_user_by_username('<the username you entered>'))
"
```
Expected: a row is printed with the username and a non-plaintext `password_hash`.

