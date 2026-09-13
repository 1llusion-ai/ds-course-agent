"""Check or explicitly rebuild the optional learner-memory Chroma index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.embeddings import create_embedding_model
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learner_memory_index import LearnerMemoryIndex


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--persist-directory", type=Path, default=Path(config.CHROMA_PERSIST_DIR))
    parser.add_argument("--apply", action="store_true", help="Rebuild the index. Default is consistency check only.")
    args = parser.parse_args()
    index = LearnerMemoryIndex(args.persist_directory, create_embedding_model())
    repository = SQLiteInteractionEpisodeRepository(args.database)
    before = index.check(repository, args.student_id)
    rebuilt = index.rebuild(repository, args.student_id) if args.apply else 0
    after = index.check(repository, args.student_id) if args.apply else before
    print(
        json.dumps(
            {
                "mode": "rebuild" if args.apply else "check",
                "rebuilt": rebuilt,
                "before": before.to_dict(),
                "after": after.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if after.consistent else 2


if __name__ == "__main__":
    raise SystemExit(main())
