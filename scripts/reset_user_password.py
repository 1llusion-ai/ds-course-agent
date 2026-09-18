#!/usr/bin/env python3
"""Reset an existing local user's password as an explicit admin action.

Example:
    python scripts/reset_user_password.py alice

The new password is entered through hidden prompts and is never written to
disk. The command requires typing the target username as a confirmation before
updating the account.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._path import ensure_src_path

ensure_src_path()

from ds_course_agent.api.auth.models import get_user_by_username, init_db, update_user_password
from ds_course_agent.api.auth.service import hash_password

MIN_PASSWORD_LENGTH = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset an existing local auth user's password")
    parser.add_argument("username")
    args = parser.parse_args(argv)

    username = args.username.strip()
    if not username:
        parser.error("username must not be blank")

    init_db()
    if get_user_by_username(username) is None:
        print(f"User {username!r} was not found; no password was changed.", file=sys.stderr)
        return 1

    print(f"Administrative password reset requested for {username!r}.")
    confirmation = input(f"Type {username!r} to confirm: ").strip()
    if confirmation != username:
        print("Confirmation did not match; no password was changed.", file=sys.stderr)
        return 1

    password = getpass.getpass("New password: ")
    password_confirmation = getpass.getpass("Repeat new password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters; no password was changed.", file=sys.stderr)
        return 1
    if password != password_confirmation:
        print("Passwords do not match; no password was changed.", file=sys.stderr)
        return 1

    updated = update_user_password(username=username, password_hash=hash_password(password))
    if updated is None:  # pragma: no cover - account deletion race is exceptional
        print(f"User {username!r} no longer exists; no password was changed.", file=sys.stderr)
        return 1

    print(f"Password reset for user {updated['username']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
