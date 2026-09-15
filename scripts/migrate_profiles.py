"""Preview or apply event-sourced learner profile snapshot projections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Write snapshots. Default is dry-run.")
    args = parser.parse_args()
    repository = SQLiteProfileSnapshotRepository(args.database)
    students = repository.list_student_ids()
    projected = 0
    verified = 0
    if args.apply:
        for student_id in students:
            repository.project(student_id)
            projected += 1
            verified += repository.verify_replay(student_id)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "student_count": len(students),
                "projected_count": projected,
                "verified_count": verified,
                "students": list(students),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
