"""Preview or import legacy JSONL learning events into teaching SQLite storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.memory_core import MemoryCore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-directory", type=Path, default=Path(config.CHAT_HISTORY_DIR))
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Import events. Default is dry-run.")
    args = parser.parse_args()
    memory = MemoryCore(base_dir=str(args.history_directory))
    files = sorted((args.history_directory / "learning_events").glob("*_events.jsonl"))
    repository = SQLiteLearningEventRepository(args.database)
    discovered = imported = skipped = invalid = 0
    for path in files:
        student_id = path.name.removesuffix("_events.jsonl")
        try:
            events = memory.load_events(student_id)
        except Exception:
            invalid += 1
            continue
        discovered += len(events)
        if not args.apply:
            continue
        for event in events:
            inserted = repository.append(LearningEventRecord(event, f"legacy:{event.event_id}"))
            imported += inserted
            skipped += not inserted
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "file_count": len(files),
                "discovered_events": discovered,
                "imported_events": imported,
                "skipped_events": skipped,
                "invalid_files": invalid,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
