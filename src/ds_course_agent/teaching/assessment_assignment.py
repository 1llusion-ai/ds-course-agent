"""Teaching policy for planning one assessment assignment."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ds_course_agent.assessment.models import (
    AssessmentLearnerEvidence,
    AssessmentPracticeError,
    CognitiveOperation,
    ComplementaryQuestionRequirement,
    Difficulty,
    GenerateQuestionsRequest,
    QuestionObjective,
    TeachingObjectiveKind,
    question_slot_id,
)
from ds_course_agent.assessment.versioning import AssessmentResourceRevision, assessment_resource_revision
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
SESSION_MAX_PREPARATIONS = 9
KC_MAX_OPPORTUNITIES = 3


class AssessmentPlanContext(BaseModel):
    """Trusted planning facts, separate from the client generation request."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    opportunity_id: str
    profile_revision: int | None = None
    source_event_cursor: str = ""
    resource_revision: AssessmentResourceRevision
    policy_version: str = "observed-practice/2"
    selection_reason: str = "course-kc-scored-evidence"


@dataclass(frozen=True)
class SessionAssessmentPlan:
    """A session-grounded KC target and the events supporting its selection."""

    display_name: str
    request: GenerateQuestionsRequest
    source_event_ids: tuple[str, ...]
    context: AssessmentPlanContext | None = None


class AssessmentAssignmentPlanner:
    """Choose one KC, difficulty, and question count from typed learner context."""

    def plan_session(
        self,
        session_id: str,
        events: Sequence[BaseEvent],
        learner_state: LearnerStateSnapshot,
        *,
        course: object | None = None,
        consumed_opportunities: Mapping[str, Collection[str]] | None = None,
        active_kc_ids: Collection[str] = (),
    ) -> tuple[SessionAssessmentPlan, ...]:
        """Select at most three new canonical KCs from this learner's session.

        Weak-spot evidence is considered first. Remaining concepts follow their
        first appearance in the session, with their latest appearance breaking
        ties. Existing preparation rows consume the session KC budget.
        """

        by_concept: defaultdict[str, list[tuple[int, BaseEvent]]] = defaultdict(list)
        nodes = {node.canonical_id: node for node in get_knowledge_map(course).nodes if node.node_type is NodeType.KC}
        for event_index, event in enumerate(events):
            if (
                event.session_id != session_id
                or event.student_id != learner_state.student_id
                or event.course_id != learner_state.course_id
                or event.event_type is not EventType.CONCEPT_MENTIONED
            ):
                continue
            concept_id = str(event.payload.get("concept_id") or "").strip()
            if concept_id in nodes:
                by_concept[concept_id].append((event_index, event))

        consumed_opportunities = consumed_opportunities or {}
        scheduled = set(consumed_opportunities)
        revision = assessment_resource_revision(str(getattr(course, "course_id", learner_state.course_id)))
        revision_token = f"{revision.graph_digest[:16]}:{revision.corpus_revision}:{revision.evidence_policy}:{revision.review_policy}"
        opportunities = {
            concept_id: max(
                (
                    (event.timestamp, event.event_id)
                    for event in events
                    if event.student_id == learner_state.student_id
                    and event.course_id == learner_state.course_id
                    and event.event_type is EventType.QUESTION_ANSWERED
                    and event.observation.concept_id == concept_id
                ),
                default=(0, "initial"),
            )[1]
            + "@"
            + revision_token
            for concept_id in by_concept
        }
        total = sum(len(items) for items in consumed_opportunities.values())
        if total >= SESSION_MAX_PREPARATIONS:
            return ()
        available = {
            concept_id
            for concept_id in by_concept
            if concept_id not in active_kc_ids
            and opportunities[concept_id] not in consumed_opportunities.get(concept_id, ())
            and len(consumed_opportunities.get(concept_id, ())) < KC_MAX_OPPORTUNITIES
            and (concept_id in scheduled or len(scheduled) < SESSION_MAX_KC_COUNT)
        }
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
        remaining_new = max(0, SESSION_MAX_KC_COUNT - len(scheduled))
        chosen = []
        for concept_id in selected:
            if concept_id in scheduled:
                chosen.append(concept_id)
            elif remaining_new:
                chosen.append(concept_id)
                remaining_new -= 1
        selected = chosen[
            : max(0, SESSION_MAX_PREPARATIONS - sum(len(items) for items in (consumed_opportunities or {}).values()))
        ]
        return tuple(
            SessionAssessmentPlan(
                display_name=nodes[concept_id].display_name,
                request=self.plan_for_concept(concept_id, learner_state, count=SESSION_ASSESSMENT_QUESTION_COUNT),
                source_event_ids=tuple(event.event_id for _, event in by_concept[concept_id]),
                context=self.plan_context(
                    learner_state,
                    opportunity_id=opportunities[concept_id],
                    course_id=str(getattr(course, "course_id", learner_state.course_id)),
                ),
            )
            for concept_id in selected
        )

    @staticmethod
    def plan_context(
        learner_state: LearnerStateSnapshot | None, *, opportunity_id: str, course_id: str | None = None
    ) -> AssessmentPlanContext:
        """Capture server-owned revisions without granting client control fields."""
        return AssessmentPlanContext(
            opportunity_id=opportunity_id,
            profile_revision=learner_state.profile_revision if learner_state else None,
            source_event_cursor=learner_state.source_event_cursor if learner_state else "",
            resource_revision=assessment_resource_revision(
                course_id or str(learner_state.course_id if learner_state else "data-science-intro")
            ),
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
        *,
        course: object | None = None,
    ) -> GenerateQuestionsRequest:
        """Build the generation request from agent-owned learning policy."""

        target_kc_id = self._target_kc_id(matched_concepts, learner_state, course=course)
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
            learner_evidence=self._learner_evidence(target_kc_id, learner_state),
            teaching_requirement=(
                self._complementary_requirement(target_kc_id, difficulty, learner_state)
                if count == SESSION_ASSESSMENT_QUESTION_COUNT
                else None
            ),
        )

    @staticmethod
    def _learner_evidence(
        target_kc_id: str, learner_state: LearnerStateSnapshot | None
    ) -> AssessmentLearnerEvidence | None:
        """Project relevant recorded facts; never infer mastery from interaction counts."""
        if learner_state is None:
            return None
        practice = learner_state.practice.get(target_kc_id)
        focus = learner_state.recent_concepts.get(target_kc_id)
        clarifications = max(
            (
                spot.clarification_count
                for spot in (*learner_state.weak_spot_candidates, *learner_state.pending_weak_spots)
                if spot.concept_id == target_kc_id
            ),
            default=0,
        )
        errors = tuple(
            AssessmentPracticeError(
                question_stem=item.question_stem,
                selected_option_text=item.selected_option_text,
                correct_option_text=item.correct_option_text,
                cognitive_operation=(
                    CognitiveOperation(item.cognitive_operation)
                    if item.cognitive_operation in {operation.value for operation in CognitiveOperation}
                    else None
                ),
            )
            for item in (practice.recent_attempts if practice else ())
            if not item.is_correct
        )[-2:]
        return AssessmentLearnerEvidence(
            course_id=str(learner_state.course_id),
            target_kc_id=target_kc_id,
            answered_count=practice.answered_count if practice else 0,
            correct_count=practice.correct_count if practice else 0,
            effective_answered_count=practice.effective_answered_count if practice else 0,
            recent_answered_count=practice.recent_answered_count if practice else 0,
            recent_correct_count=practice.recent_correct_count if practice else 0,
            mention_count=focus.mention_count if focus else 0,
            clarification_count=clarifications,
            recent_errors=errors,
        )

    @staticmethod
    def _complementary_requirement(
        target_kc_id: str, difficulty: Difficulty, learner_state: LearnerStateSnapshot | None = None
    ) -> ComplementaryQuestionRequirement:
        operation = CognitiveOperation.ANALYSIS if difficulty is Difficulty.ADVANCED else CognitiveOperation.APPLICATION
        distinction_operation = (
            CognitiveOperation.ANALYSIS if difficulty is Difficulty.ADVANCED else CognitiveOperation.INTERPRETATION
        )
        practice = learner_state.practice.get(target_kc_id) if learner_state is not None else None
        focus = practice.last_incorrect_operation if practice is not None else None
        distinction_objective = "区分目标知识点与最容易混淆的概念、条件或适用边界。"
        transfer_objective = "把目标知识点迁移到新的具体情境并判断结果或方法选择。"
        if focus == CognitiveOperation.INTERPRETATION.value:
            distinction_objective += "优先澄清学生最近答错的关系解释或适用边界。"
        elif focus == CognitiveOperation.APPLICATION.value:
            transfer_objective += "优先修复学生最近答错的情境迁移或方法选择。"
        return ComplementaryQuestionRequirement(
            target_kc_id=target_kc_id,
            objectives=(
                QuestionObjective(
                    slot_id=question_slot_id(target_kc_id, 0),
                    kind=TeachingObjectiveKind.CONCEPT_DISTINCTION,
                    operation=distinction_operation,
                    objective=distinction_objective,
                ),
                QuestionObjective(
                    slot_id=question_slot_id(target_kc_id, 1),
                    kind=TeachingObjectiveKind.APPLICATION_TRANSFER,
                    operation=operation,
                    objective=transfer_objective,
                ),
            ),
        )

    @staticmethod
    def _target_kc_id(
        matched_concepts: Sequence[object],
        learner_state: LearnerStateSnapshot | None,
        *,
        course: object | None = None,
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
            (node.canonical_id for node in get_knowledge_map(course).nodes if node.node_type is NodeType.KC), None
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
            if practice.recommended_difficulty is not None:
                return Difficulty(practice.recommended_difficulty)
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
