#!/usr/bin/env python3
"""Explicit local administrator bootstrap and one-shot legacy registration migration.

Examples:
    python scripts/admin.py bootstrap alice --confirm alice
    python scripts/admin.py import-registration --confirm import-registration

Without --confirm this command prints a plan and does not open the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._path import ensure_src_path

ensure_src_path()

from dotenv import dotenv_values

from ds_course_agent.api.auth.contracts import AuthOperationError, RegistrationMode
from ds_course_agent.api.auth.models import bootstrap_admin
from ds_course_agent.api.auth.registration import import_legacy_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap", help="grant an existing account administrator access")
    bootstrap.add_argument("username")
    bootstrap.add_argument("--confirm")
    legacy = sub.add_parser("import-registration", help="import old environment registration settings once")
    legacy.add_argument("--confirm")
    args = parser.parse_args(argv)
    expected = args.username if args.command == "bootstrap" else "import-registration"
    if args.confirm != expected:
        print(f"Plan: {args.command}. No data changed. Re-run with --confirm {expected!r} to apply.")
        return 0
    try:
        if args.command == "bootstrap":
            user = bootstrap_admin(args.username)
            print(f"Administrator access enabled for {user.username!r}; previous sessions revoked.")
        else:
            # Legacy fields are read only by this explicit one-shot command.
            legacy = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
            import_legacy_policy(
                mode=RegistrationMode(legacy.get("AUTH_REGISTRATION_MODE", "closed")),
                code=legacy.get("AUTH_INVITE_CODE", "").strip(),
                expires_at=legacy.get("AUTH_INVITE_EXPIRES_AT", "").strip() or None,
                max_users=int(legacy.get("AUTH_MAX_USERS", "0")),
            )
            print("Legacy registration policy imported. Future changes belong to the admin console.")
    except (AuthOperationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
