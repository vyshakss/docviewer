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
