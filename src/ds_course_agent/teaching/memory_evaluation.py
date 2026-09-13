"""Offline evaluation for structured learner-memory recall."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ds_course_agent.teaching.learner_state import LearnerStateSnapshot
from ds_course_agent.teaching.personalization import LearnerMemoryRetriever


@dataclass(frozen=True)
class RecallCase:
    student_id: str
    target_concept_ids: tuple[str, ...]
    expected_episode_ids: tuple[str, ...] = ()
    expected_assessment_question_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecallCase:
        return cls(
            student_id=str(data["student_id"]),
            target_concept_ids=tuple(str(item) for item in data.get("target_concept_ids", ())),
            expected_episode_ids=tuple(str(item) for item in data.get("expected_episode_ids", ())),
            expected_assessment_question_ids=tuple(
                str(item) for item in data.get("expected_assessment_question_ids", ())
            ),
        )


@dataclass(frozen=True)
class RecallEvaluation:
    case_count: int
    episode_recall_at_k: float
    assessment_recall_at_k: float
    cross_student_violations: int
    missed_episode_ids: tuple[str, ...]
    missed_assessment_question_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "episode_recall_at_k": self.episode_recall_at_k,
            "assessment_recall_at_k": self.assessment_recall_at_k,
            "cross_student_violations": self.cross_student_violations,
            "missed_episode_ids": list(self.missed_episode_ids),
            "missed_assessment_question_ids": list(self.missed_assessment_question_ids),
        }


def load_recall_cases(path: str | Path) -> tuple[RecallCase, ...]:
    """Load JSON or JSONL cases without importing runtime or model code."""

    raw = Path(path).read_text(encoding="utf-8")
    data = (
        json.loads(raw)
        if Path(path).suffix == ".json"
        else [json.loads(line) for line in raw.splitlines() if line.strip()]
    )
    if isinstance(data, dict):
        data = data.get("cases", ())
    return tuple(RecallCase.from_dict(item) for item in data)


def evaluate_recall(retriever: LearnerMemoryRetriever, cases: tuple[RecallCase, ...]) -> RecallEvaluation:
    """Measure expected evidence coverage and enforce student isolation."""

    missed_episodes: list[str] = []
    missed_questions: list[str] = []
    episode_total = question_total = episode_hit = question_hit = 0
    violations = 0
    for case in cases:
        context = retriever.retrieve(
            case.student_id,
            target_concept_ids=case.target_concept_ids,
            learner_state=LearnerStateSnapshot(student_id=case.student_id),
        )
        episode_ids = {item.episode_id for item in context.interaction_episodes}
        question_ids = {item.question_id for item in context.assessment_evidence}
        violations += sum(item.student_id != case.student_id for item in context.interaction_episodes)
        episode_total += len(case.expected_episode_ids)
        question_total += len(case.expected_assessment_question_ids)
        episode_hit += sum(item in episode_ids for item in case.expected_episode_ids)
        question_hit += sum(item in question_ids for item in case.expected_assessment_question_ids)
        missed_episodes.extend(item for item in case.expected_episode_ids if item not in episode_ids)
        missed_questions.extend(item for item in case.expected_assessment_question_ids if item not in question_ids)
    return RecallEvaluation(
        case_count=len(cases),
        episode_recall_at_k=episode_hit / episode_total if episode_total else 1.0,
        assessment_recall_at_k=question_hit / question_total if question_total else 1.0,
        cross_student_violations=violations,
        missed_episode_ids=tuple(dict.fromkeys(missed_episodes)),
        missed_assessment_question_ids=tuple(dict.fromkeys(missed_questions)),
    )


__all__ = ["RecallCase", "RecallEvaluation", "evaluate_recall", "load_recall_cases"]
