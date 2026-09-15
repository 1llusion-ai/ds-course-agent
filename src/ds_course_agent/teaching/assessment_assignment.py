"""Teaching policy for planning one assessment assignment."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from ds_course_agent.assessment.models import (
    CognitiveOperation,
    ComplementaryQuestionRequirement,
    Difficulty,
    GenerateQuestionsRequest,
    QuestionObjective,
    TeachingObjectiveKind,
    question_slot_id,
)
from ds_course_agent.teaching.knowledge_map import NodeType, get_knowledge_map
from ds_course_agent.teaching.learner_state import (
    LearnerStateSnapshot,
    rank_active_weak_spots,
    rank_recent_concepts,
)
from ds_course_agent.teaching.learning_events import BaseEvent, EventType
from ds_course_agent.teaching.practice import PracticeLevel

DEFAULT_ASSESSMENT_QUESTION_COUNT = 5
SESSION_ASSESSMENT_QUESTION_COUNT = 2
SESSION_MAX_KC_COUNT = 3


@dataclass(frozen=True)
class SessionAssessmentPlan:
    """A session-grounded KC target and the events supporting its selection."""

    display_name: str
    request: GenerateQuestionsRequest
    source_event_ids: tuple[str, ...]


class AssessmentAssignmentPlanner:
    """Choose one KC, difficulty, and question count from typed learner context."""

    def plan_session(
        self,
        session_id: str,
        events: Sequence[BaseEvent],
        learner_state: LearnerStateSnapshot,
        *,
        scheduled_kc_ids: Collection[str] = (),
    ) -> tuple[SessionAssessmentPlan, ...]:
        """Select at most three new canonical KCs from this learner's session.

        Weak-spot evidence is considered first. Remaining concepts follow their
        first appearance in the session, with their latest appearance breaking
        ties. Existing preparation rows consume the session KC budget.
        """

        by_concept: defaultdict[str, list[tuple[int, BaseEvent]]] = defaultdict(list)
        nodes = {node.canonical_id: node for node in get_knowledge_map().nodes if node.node_type is NodeType.KC}
        for event_index, event in enumerate(events):
            if (
                event.session_id != session_id
                or event.student_id != learner_state.student_id
                or event.event_type is not EventType.CONCEPT_MENTIONED
            ):
                continue
            concept_id = str(event.payload.get("concept_id") or "").strip()
            if concept_id in nodes:
                by_concept[concept_id].append((event_index, event))

        scheduled = {str(concept_id).strip() for concept_id in scheduled_kc_ids if str(concept_id).strip()}
        available = set(by_concept) - scheduled
        selected: list[str] = []
        for weak_spot in (*rank_active_weak_spots(learner_state), *learner_state.pending_weak_spots):
            if weak_spot.concept_id in available and weak_spot.concept_id not in selected:
                selected.append(weak_spot.concept_id)
        selected.extend(
            concept_id
            for concept_id in sorted(
                available - set(selected),
                key=lambda item: self._session_event_order(by_concept[item]),
            )
        )
        selected = selected[: max(0, SESSION_MAX_KC_COUNT - len(scheduled))]
        return tuple(
            SessionAssessmentPlan(
                display_name=nodes[concept_id].display_name,
                request=self.plan_for_concept(concept_id, learner_state, count=SESSION_ASSESSMENT_QUESTION_COUNT),
                source_event_ids=tuple(event.event_id for _, event in by_concept[concept_id]),
            )
            for concept_id in selected
        )

    @staticmethod
    def _session_event_order(records: Sequence[tuple[int, BaseEvent]]) -> tuple[float, float, int, str]:
        first_index, _ = records[0]
        latest_index, latest_event = records[-1]
        latest_timestamp = max(event.timestamp for _, event in records)
        return (first_index, -latest_timestamp, -latest_index, records[0][1].payload.get("concept_id", ""))

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

        difficulty = self._difficulty(target_kc_id, learner_state)
        return GenerateQuestionsRequest(
            target_kc_id=target_kc_id,
            difficulty=difficulty,
            count=count,
            teaching_requirement=(
                self._complementary_requirement(target_kc_id, difficulty)
                if count == SESSION_ASSESSMENT_QUESTION_COUNT
                else None
            ),
        )

    @staticmethod
    def _complementary_requirement(target_kc_id: str, difficulty: Difficulty) -> ComplementaryQuestionRequirement:
        operation = CognitiveOperation.ANALYSIS if difficulty is Difficulty.ADVANCED else CognitiveOperation.APPLICATION
        distinction_operation = (
            CognitiveOperation.ANALYSIS if difficulty is Difficulty.ADVANCED else CognitiveOperation.INTERPRETATION
        )
        return ComplementaryQuestionRequirement(
            target_kc_id=target_kc_id,
            objectives=(
                QuestionObjective(
                    slot_id=question_slot_id(target_kc_id, 0),
                    kind=TeachingObjectiveKind.CONCEPT_DISTINCTION,
                    operation=distinction_operation,
                    objective="区分目标知识点与最容易混淆的概念、条件或适用边界。",
                ),
                QuestionObjective(
                    slot_id=question_slot_id(target_kc_id, 1),
                    kind=TeachingObjectiveKind.APPLICATION_TRANSFER,
                    operation=operation,
                    objective="把目标知识点迁移到新的具体情境并判断结果或方法选择。",
                ),
            ),
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


__all__ = [
    "AssessmentAssignmentPlanner",
    "DEFAULT_ASSESSMENT_QUESTION_COUNT",
    "SESSION_ASSESSMENT_QUESTION_COUNT",
    "SESSION_MAX_KC_COUNT",
]
