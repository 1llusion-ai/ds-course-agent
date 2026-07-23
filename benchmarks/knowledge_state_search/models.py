"""Typed data models for the knowledge-state search probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RequirementKind = Literal["core", "prerequisite", "misconception", "goal"]


@dataclass(frozen=True)
class StudentProfile:
    """Minimal student state used by the research prototype."""

    student_id: str
    level: str
    mastered_concepts: tuple[str, ...] = ()
    weak_concepts: tuple[str, ...] = ()
    misconceptions: tuple[str, ...] = ()
    learning_goal: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StudentProfile:
        """Build a profile from JSON-compatible data."""

        return cls(
            student_id=str(payload.get("student_id", "")),
            level=str(payload.get("level", "")),
            mastered_concepts=tuple(str(item) for item in payload.get("mastered_concepts", [])),
            weak_concepts=tuple(str(item) for item in payload.get("weak_concepts", [])),
            misconceptions=tuple(str(item) for item in payload.get("misconceptions", [])),
            learning_goal=str(payload.get("learning_goal", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "student_id": self.student_id,
            "level": self.level,
            "mastered_concepts": list(self.mastered_concepts),
            "weak_concepts": list(self.weak_concepts),
            "misconceptions": list(self.misconceptions),
            "learning_goal": self.learning_goal,
        }


@dataclass(frozen=True)
class EvidenceRequirement:
    """One claim or teaching obligation that a search should cover."""

    requirement_id: str
    kind: RequirementKind
    concept: str
    description: str
    search_terms: tuple[str, ...] = ()
    hard: bool = False
    priority: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceRequirement:
        """Build a requirement from JSON-compatible data."""

        return cls(
            requirement_id=str(payload["requirement_id"]),
            kind=payload["kind"],
            concept=str(payload["concept"]),
            description=str(payload["description"]),
            search_terms=tuple(str(item) for item in payload.get("search_terms", [])),
            hard=bool(payload.get("hard", False)),
            priority=int(payload.get("priority", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "concept": self.concept,
            "description": self.description,
            "search_terms": list(self.search_terms),
            "hard": self.hard,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class SearchTask:
    """A paired question used to test profile-conditioned search planning."""

    task_id: str
    question: str
    target_concepts: tuple[str, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    profiles: tuple[StudentProfile, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SearchTask:
        """Build a search task from JSON-compatible data."""

        return cls(
            task_id=str(payload["task_id"]),
            question=str(payload["question"]),
            target_concepts=tuple(str(item) for item in payload.get("target_concepts", [])),
            evidence_requirements=tuple(
                EvidenceRequirement.from_dict(item) for item in payload["evidence_requirements"]
            ),
            profiles=tuple(StudentProfile.from_dict(item) for item in payload["profiles"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "task_id": self.task_id,
            "question": self.question,
            "target_concepts": list(self.target_concepts),
            "evidence_requirements": [item.to_dict() for item in self.evidence_requirements],
            "profiles": [item.to_dict() for item in self.profiles],
        }


@dataclass(frozen=True)
class EvidenceGap:
    """Structured learner-conditioned evidence obligations."""

    core_requirements: tuple[EvidenceRequirement, ...] = ()
    learner_requirements: tuple[EvidenceRequirement, ...] = ()
    satisfied_prerequisites: tuple[str, ...] = ()

    @property
    def all_requirements(self) -> tuple[EvidenceRequirement, ...]:
        """Return hard core obligations followed by learner obligations."""

        return self.core_requirements + self.learner_requirements

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "core_requirements": [item.to_dict() for item in self.core_requirements],
            "learner_requirements": [item.to_dict() for item in self.learner_requirements],
            "satisfied_prerequisites": list(self.satisfied_prerequisites),
        }
