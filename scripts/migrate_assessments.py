"""Inspect or apply normalized assessment storage migration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.database import migrate_assessment_database, plan_assessment_database


def _counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("assessments", "assessments_legacy", "assessment_questions", "assessment_answers")
            if table in tables
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(config.ASSESSMENT_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Apply migration. Default is dry-run.")
    args = parser.parse_args()
    before = _counts(args.database)
    plan = plan_assessment_database(args.database)
    applied = migrate_assessment_database(args.database) if args.apply else ()
    after = _counts(args.database) if args.apply else before
    final_plan = plan_assessment_database(args.database) if args.apply else plan
    print(
        json.dumps(
            {
                "database": str(args.database.resolve()),
                "mode": "apply" if args.apply else "dry-run",
                "applied_versions": list(plan.applied_versions)
                if not args.apply
                else [item.version for item in applied],
                "pending_versions": [item.version for item in final_plan.pending],
                "before": before,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
