#!/usr/bin/env python3
"""Create or update a local login account.

Example:
    python scripts/create_user.py alice 'secret-password' student_001 'Alice'

The account is stored in AUTH_DB_PATH (default: var/auth.db). Passwords are
bcrypt-hashed; plaintext passwords are never written to disk.
"""

from __future__ import annotations

import argparse

from scripts._path import ensure_src_path

ensure_src_path()

from ds_course_agent.api.auth.models import create_or_update_user, init_db
from ds_course_agent.api.auth.service import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a local auth user")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("student_id")
    parser.add_argument("display_name")
    args = parser.parse_args()

    init_db()
    user = create_or_update_user(
        username=args.username,
        password_hash=hash_password(args.password),
        student_id=args.student_id,
        display_name=args.display_name,
    )
    print(f"Created/updated user {user['username']} for student_id={user['student_id']}")


if __name__ == "__main__":
    main()
