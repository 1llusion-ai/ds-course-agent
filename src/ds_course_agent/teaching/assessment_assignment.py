"""Teaching policy for planning one assessment assignment."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ds_course_agent.assessment.models import Difficulty, GenerateQuestionsRequest
from ds_course_agent.teaching.knowledge_map import NodeType, get_knowledge_map
from ds_course_agent.teaching.learner_state import (
    LearnerStateSnapshot,
    rank_active_weak_spots,
    rank_recent_concepts,
)
from ds_course_agent.teaching.learning_events import BaseEvent, EventType
from ds_course_agent.teaching.practice import PracticeLevel

DEFAULT_ASSESSMENT_QUESTION_COUNT = 5


@dataclass(frozen=True)
class SessionAssessmentPlan:
    """A session-grounded KC target and the events supporting its selection."""

    display_name: str
    request: GenerateQuestionsRequest
    source_event_ids: tuple[str, ...]


class AssessmentAssignmentPlanner:
    """Choose one KC, difficulty, and question count from typed learner context."""

    def plan_session(
        self, session_id: str, events: Sequence[BaseEvent], learner_state: LearnerStateSnapshot
    ) -> tuple[SessionAssessmentPlan, ...]:
        """Select canonical KCs discussed in this learner's session, never from other sessions."""

        by_concept = defaultdict(list)
        for event in events:
            if (
                event.session_id == session_id
                and event.student_id == learner_state.student_id
                and event.event_type is EventType.CONCEPT_MENTIONED
            ):
                by_concept[event.payload.get("concept_id")].append(event.event_id)
        nodes = {node.canonical_id: node for node in get_knowledge_map().nodes if node.node_type is NodeType.KC}
        return tuple(
            SessionAssessmentPlan(
                display_name=nodes[concept_id].display_name,
                request=self.plan_for_concept(concept_id, learner_state, count=2),
                source_event_ids=tuple(dict.fromkeys(event_ids)),
            )
            for concept_id, event_ids in by_concept.items()
            if concept_id in nodes
        )

    def plan(
        self,
        matched_concepts: Sequence[object],
        learner_state: LearnerStateSnapshot | None,
    ) -> GenerateQuestionsRequest:
        """Build the generation request from agent-owned learning policy."""

        target_kc_id = self._target_kc_id(matched_concepts, learner_state)
        return self.plan_for_concept(target_kc_id, learner_state)

    def plan_for_concept(
        self,
        target_kc_id: str,
        learner_state: LearnerStateSnapshot | None,
        *,
        count: int = DEFAULT_ASSESSMENT_QUESTION_COUNT,
    ) -> GenerateQuestionsRequest:
        """Choose difficulty from observed evidence for an already selected KC."""

        return GenerateQuestionsRequest(
            target_kc_id=target_kc_id,
            difficulty=self._difficulty(target_kc_id, learner_state),
            count=count,
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
        fallback = next(
            (node.canonical_id for node in get_knowledge_map().nodes if node.node_type is NodeType.KC), None
        )
        if fallback is None:
            raise ValueError("course knowledge map contains no KC nodes")
        return fallback

    @staticmethod
    def _difficulty(target_kc_id: str, learner_state: LearnerStateSnapshot | None) -> Difficulty:
        if learner_state is None:
            return Difficulty.BASIC
        practice = learner_state.practice.get(target_kc_id)
        if practice is not None:
            if practice.level is PracticeLevel.READY_FOR_EXTENSION:
                return Difficulty.ADVANCED
            if practice.level is PracticeLevel.PRACTICED and practice.recent_answered_count >= 2:
                return Difficulty.INTERMEDIATE
            return Difficulty.BASIC
        if any(spot.concept_id == target_kc_id for spot in learner_state.weak_spot_candidates):
            return Difficulty.BASIC
        if any(spot.concept_id == target_kc_id for spot in learner_state.pending_weak_spots):
            return Difficulty.BASIC
        return Difficulty.BASIC


__all__ = ["AssessmentAssignmentPlanner", "DEFAULT_ASSESSMENT_QUESTION_COUNT"]
