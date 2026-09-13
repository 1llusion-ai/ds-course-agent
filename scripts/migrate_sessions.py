"""Dry-run or apply the one-time legacy session/message backfill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.api.session_backfill import apply_session_backfill, build_session_backfill_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path, default=Path(config.CHAT_HISTORY_DIR))
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Apply the backfill. Default is dry-run.")
    args = parser.parse_args()

    plan = build_session_backfill_plan(args.history_dir)
    result = plan.summary()
    if args.apply:
        result.update(apply_session_backfill(plan, database=args.database))
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "history_dir": str(args.history_dir.resolve()),
                "database": str(args.database.resolve()),
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
