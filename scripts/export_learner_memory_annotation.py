"""Export small, human-reviewable learner-memory annotation candidates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import EventType, QuestionAnsweredEvent
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository


def _episode_candidate(source, candidate) -> dict:
    overlap = sorted(set(source.concept_ids) & set(candidate.concept_ids))
    return {
        "type": "interaction_episode",
        "id": candidate.episode_id,
        "relevance": None,
        "auto_reason": f"same_concept:{','.join(overlap)}; outcome:{candidate.outcome.value}",
        "question": candidate.learner_question,
        "concept_ids": list(candidate.concept_ids),
        "outcome": candidate.outcome.value,
        "updated_at": candidate.updated_at.isoformat(),
    }


def build_annotation_cases(database: Path, *, student_id: str | None = None, limit: int = 20) -> tuple[dict, ...]:
    """Build cases from same-student history; labels remain empty for humans."""

    episodes = SQLiteInteractionEpisodeRepository(database)
    events = SQLiteLearningEventRepository(database)
    students = (student_id,) if student_id else SQLiteProfileSnapshotRepository(database).list_student_ids()
    cases: list[dict] = []
    for current_student in students:
        all_episodes = episodes.list_for_student(current_student, limit=100)
        for source in all_episodes:
            if (
                not source.concept_ids
                or not source.learner_question.strip()
                or source.episode_id.startswith("assessment_episode:")
                or source.learner_question.startswith("assessment:")
            ):
                continue
            candidates = [
                item
                for item in all_episodes
                if item.episode_id != source.episode_id and set(item.concept_ids) & set(source.concept_ids)
            ]
            candidates.sort(
                key=lambda item: (
                    item.outcome.value not in {"continued_clarification", "explicit_negative_feedback"},
                    -item.updated_at.timestamp(),
                    item.episode_id,
                )
            )
            evidence = [
                record.event
                for record in events.list_for_student(
                    current_student,
                    event_types=(EventType.QUESTION_ANSWERED,),
                    concept_ids=source.concept_ids,
                    limit=20,
                )
                if isinstance(record.event, QuestionAnsweredEvent)
            ]
            assessment_candidates = [
                {
                    "type": "assessment_question",
                    "id": event.observation.question_id,
                    "relevance": None,
                    "auto_reason": f"same_concept:{event.observation.concept_id}; correct:{event.observation.is_correct}",
                    "question": None,
                    "concept_ids": [event.observation.concept_id],
                    "outcome": "correct_assessment" if event.observation.is_correct else "incorrect_assessment",
                    "updated_at": datetime.fromtimestamp(event.timestamp).isoformat(),
                }
                for event in evidence
            ]
            candidate_rows = [_episode_candidate(source, item) for item in candidates[:4]] + assessment_candidates[:2]
            if not candidate_rows:
                continue
            cases.append(
                {
                    "case_id": f"{current_student}:{source.episode_id}",
                    "student_id": current_student,
                    "query": source.learner_question,
                    "target_concept_ids": list(source.concept_ids),
                    "candidates": candidate_rows,
                    "annotation": {"relevant_ids": [], "notes": "请将最相关候选的 relevance 填为 3/2/0"},
                }
            )
            if len(cases) >= limit:
                return tuple(cases)
    return tuple(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    parser.add_argument("--student-id")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, help="Write JSONL here; default is stdout.")
    args = parser.parse_args()
    cases = build_annotation_cases(args.database, student_id=args.student_id, limit=max(1, args.limit))
    text = "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + ("\n" if cases else "")
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
