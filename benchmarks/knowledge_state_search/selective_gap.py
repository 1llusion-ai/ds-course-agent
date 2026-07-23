"""Counterfactual trigger gating for predicted learner obligations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from benchmarks.knowledge_state_search.models import (
    EvidenceGap,
    EvidenceRequirement,
    SearchTask,
    StudentProfile,
)
from benchmarks.knowledge_state_search.prompt_probe import _core_gap

TriggerField = Literal["weak_concept", "misconception", "learning_goal"]


@dataclass(frozen=True)
class ObligationTrigger:
    """Typed profile fact claimed to cause a learner obligation."""

    field: TriggerField
    value: str


@dataclass(frozen=True)
class PredictedObligation:
    """Predicted learner obligation before conversion to planner requirements."""

    kind: Literal["prerequisite", "misconception", "goal"]
    concept: str
    claim: str
    search_terms: tuple[str, ...]
    trigger: ObligationTrigger
    priority: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PredictedObligation:
        """Build a typed obligation from validated predictor JSON."""

        trigger = payload["trigger"]
        return cls(
            kind=payload["kind"],
            concept=str(payload["concept"]),
            claim=str(payload["claim"]),
            search_terms=tuple(str(item) for item in payload.get("search_terms", [])),
            trigger=ObligationTrigger(
                field=trigger["field"],
                value=str(trigger["value"]),
            ),
            priority=int(payload.get("priority", 1)),
        )


def parse_obligations(prediction: dict[str, Any]) -> tuple[PredictedObligation, ...]:
    """Parse predictor output after schema validation."""

    return tuple(PredictedObligation.from_dict(item) for item in prediction.get("obligations", []))


def neutralize_trigger(profile: StudentProfile, trigger: ObligationTrigger) -> StudentProfile:
    """Create a profile where exactly one claimed trigger is neutralized."""

    mastered = profile.mastered_concepts
    weak = profile.weak_concepts
    misconceptions = profile.misconceptions
    learning_goal = profile.learning_goal
    if trigger.field == "weak_concept":
        weak = tuple(item for item in weak if item != trigger.value)
        mastered = tuple(dict.fromkeys((*mastered, trigger.value)))
    elif trigger.field == "misconception":
        misconceptions = tuple(item for item in misconceptions if item != trigger.value)
    else:
        learning_goal = ""
    return StudentProfile(
        student_id=f"{profile.student_id}_neutralized_{trigger.field}",
        level=profile.level,
        mastered_concepts=mastered,
        weak_concepts=weak,
        misconceptions=misconceptions,
        learning_goal=learning_goal,
    )


def select_counterfactual_obligations(
    original: tuple[PredictedObligation, ...],
    counterfactuals: dict[ObligationTrigger, tuple[PredictedObligation, ...]],
) -> tuple[PredictedObligation, ...]:
    """Keep obligations that disappear when their claimed trigger is neutralized."""

    selected: list[PredictedObligation] = []
    for obligation in original:
        counterfactual = counterfactuals.get(obligation.trigger, ())
        if not any(_same_obligation(obligation, candidate) for candidate in counterfactual):
            selected.append(obligation)
    return tuple(selected)


def obligations_to_gap(
    task: SearchTask,
    obligations: tuple[PredictedObligation, ...],
    *,
    id_prefix: str,
) -> EvidenceGap:
    """Convert selected obligations to planner-visible requirements."""

    learner = tuple(
        EvidenceRequirement(
            requirement_id=f"{id_prefix}_{index:02d}",
            kind=item.kind,
            concept=item.concept,
            description=item.claim,
            search_terms=item.search_terms,
            hard=False,
            priority=item.priority,
        )
        for index, item in enumerate(obligations, 1)
    )
    return EvidenceGap(
        core_requirements=_core_gap(task).core_requirements,
        learner_requirements=learner,
    )


def _same_obligation(left: PredictedObligation, right: PredictedObligation) -> bool:
    if _normalize(left.concept) == _normalize(right.concept):
        return True
    left_terms = {_normalize(left.concept), *(_normalize(item) for item in left.search_terms)}
    right_text = _normalize(" ".join((right.concept, right.claim, *right.search_terms)))
    return any(term and term in right_text for term in left_terms)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())
