"""Inspect or apply application database migrations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.api.session_repository import SESSION_MIGRATIONS
from ds_course_agent.shared.database import SQLiteMigrationRunner
from ds_course_agent.teaching.database import (
    LEARNER_MEMORY_MIGRATIONS,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Apply pending migrations. Default is dry-run.")
    args = parser.parse_args()

    migrations = LEARNER_MEMORY_MIGRATIONS + SESSION_MIGRATIONS
    runner = SQLiteMigrationRunner(args.database)
    before = runner.plan(migrations)
    applied = runner.apply(migrations) if args.apply else ()
    after = runner.plan(migrations) if args.apply else before
    print(
        json.dumps(
            {
                "database": str(args.database.resolve()),
                "mode": "apply" if args.apply else "dry-run",
                "applied_versions": list(after.applied_versions),
                "newly_applied": [migration.version for migration in applied],
                "pending_versions": [migration.version for migration in after.pending],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
