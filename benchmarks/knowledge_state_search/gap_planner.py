"""Deterministic evidence-obligation planner for the validation experiment."""

from __future__ import annotations

from benchmarks.knowledge_state_search.models import EvidenceGap, EvidenceRequirement, SearchTask, StudentProfile


class KnowledgeStateGapPlanner:
    """Separate profile-invariant facts from learner-specific teaching evidence."""

    def plan(self, task: SearchTask, profile: StudentProfile) -> EvidenceGap:
        """Compute the evidence obligations for one question/profile pair."""

        core = tuple(item for item in task.evidence_requirements if item.kind == "core")
        learner: list[EvidenceRequirement] = []
        satisfied: list[str] = []

        mastered = set(profile.mastered_concepts)
        weak = set(profile.weak_concepts)
        misconceptions = set(profile.misconceptions)

        for item in task.evidence_requirements:
            if item.kind == "prerequisite":
                if item.concept in weak or item.concept in misconceptions or item.concept not in mastered:
                    learner.append(item)
                else:
                    satisfied.append(item.concept)
            elif item.kind == "misconception" and item.concept in misconceptions:
                learner.append(item)
            elif item.kind == "goal" and _goal_requires(item, profile.learning_goal):
                learner.append(item)

        learner.sort(key=lambda item: (-item.priority, item.requirement_id))
        return EvidenceGap(
            core_requirements=core,
            learner_requirements=tuple(learner),
            satisfied_prerequisites=tuple(sorted(satisfied)),
        )


def _goal_requires(requirement: EvidenceRequirement, learning_goal: str) -> bool:
    """Match a small controlled vocabulary for the probe's goal conditions."""

    goal = learning_goal.lower()
    if requirement.concept == "formalism":
        return any(token in goal for token in ("公式", "formal", "数学", "推导"))
    if requirement.concept == "example":
        return any(token in goal for token in ("直观", "例子", "example", "应用"))
    return True
