"""Evaluate structured learner-memory recall from a JSON/JSONL case set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.memory_evaluation import evaluate_recall, load_recall_cases
from ds_course_agent.teaching.personalization import SQLiteLearnerMemoryRetriever


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    args = parser.parse_args()
    result = evaluate_recall(
        SQLiteLearnerMemoryRetriever(
            SQLiteInteractionEpisodeRepository(args.database), SQLiteLearningEventRepository(args.database)
        ),
        load_recall_cases(args.cases),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.cross_student_violations == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
