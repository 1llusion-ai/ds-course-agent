"""Teaching policy for planning one assessment assignment."""

from __future__ import annotations

from collections.abc import Sequence

from ds_course_agent.assessment.models import Difficulty, GenerateQuestionsRequest
from ds_course_agent.teaching.knowledge_map import NodeType, get_knowledge_map
from ds_course_agent.teaching.learner_state import (
    LearnerStateSnapshot,
    rank_active_weak_spots,
    rank_recent_concepts,
)

DEFAULT_ASSESSMENT_QUESTION_COUNT = 5


class AssessmentAssignmentPlanner:
    """Choose one KC, difficulty, and question count from typed learner context."""

    def plan(
        self,
        matched_concepts: Sequence[object],
        learner_state: LearnerStateSnapshot | None,
    ) -> GenerateQuestionsRequest:
        """Build the generation request from agent-owned learning policy."""

        target_kc_id = self._target_kc_id(matched_concepts, learner_state)
        return GenerateQuestionsRequest(
            target_kc_id=target_kc_id,
            difficulty=self._difficulty(target_kc_id, learner_state),
            count=DEFAULT_ASSESSMENT_QUESTION_COUNT,
        )

    @staticmethod
    def _target_kc_id(
        matched_concepts: Sequence[object],
        learner_state: LearnerStateSnapshot | None,
    ) -> str:
        for concept in matched_concepts:
            concept_id = str(getattr(concept, "concept_id", "") or "").strip()
            if concept_id:
                return concept_id
        if learner_state is not None:
            active = rank_active_weak_spots(learner_state)
            if active:
                return active[0].concept_id
            if learner_state.pending_weak_spots:
                return learner_state.pending_weak_spots[0].concept_id
            recent = rank_recent_concepts(learner_state)
            if recent:
                return recent[0].concept_id
        return next(node.canonical_id for node in get_knowledge_map().nodes if node.node_type is NodeType.KC)

    @staticmethod
    def _difficulty(target_kc_id: str, learner_state: LearnerStateSnapshot | None) -> Difficulty:
        if learner_state is None:
            return Difficulty.BASIC
        if any(spot.concept_id == target_kc_id for spot in learner_state.weak_spot_candidates):
            return Difficulty.BASIC
        if any(spot.concept_id == target_kc_id for spot in learner_state.pending_weak_spots):
            return Difficulty.BASIC
        if any(spot.concept_id == target_kc_id for spot in learner_state.resolved_weak_spots):
            return Difficulty.ADVANCED
        focus = learner_state.recent_concepts.get(target_kc_id)
        if focus is not None and focus.mention_count >= 3:
            return Difficulty.INTERMEDIATE
        return Difficulty.BASIC


__all__ = ["AssessmentAssignmentPlanner", "DEFAULT_ASSESSMENT_QUESTION_COUNT"]
