"""Counterfactual no-gap/single-gap profiles for the fixed-snapshot experiment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from benchmarks.knowledge_state_search.models import (
    EvidenceGap,
    SearchTask,
    StudentProfile,
)

GapKind = Literal["prerequisite", "misconception", "goal"]


@dataclass(frozen=True)
class ControlledGapSpec:
    """One preregistered learner factor for a task."""

    kind: GapKind
    value: str
    learning_goal: str = "理解算法原理"


_GAP_SPECS: dict[str, ControlledGapSpec] = {
    "kmeans_initialization": ControlledGapSpec(kind="prerequisite", value="初始化"),
    "overfitting_generalization": ControlledGapSpec(
        kind="misconception",
        value="训练准确率等于泛化能力",
    ),
    "pca_covariance": ControlledGapSpec(
        kind="goal",
        value="formalism",
        learning_goal="理解公式和推导",
    ),
    "svm_kernel": ControlledGapSpec(kind="prerequisite", value="特征空间"),
}

_WRONG_REQUIREMENT_IDS = {
    "kmeans_initialization": "misconception_global_optimum",
    "overfitting_generalization": "prereq_regularization",
    "pca_covariance": "prereq_eigenvector",
    "svm_kernel": "goal_compare",
}


def controlled_profiles(task: SearchTask) -> tuple[StudentProfile, StudentProfile]:
    """Return a no-gap/single-gap pair differing in one preregistered factor."""

    try:
        spec = _GAP_SPECS[task.task_id]
    except KeyError as exc:
        raise ValueError(f"task has no controlled gap spec: {task.task_id}") from exc

    prerequisite_concepts = tuple(item.concept for item in task.evidence_requirements if item.kind == "prerequisite")
    mastered = tuple(dict.fromkeys((*task.target_concepts, *prerequisite_concepts)))
    no_gap = StudentProfile(
        student_id=f"{task.task_id}_nogap",
        level="intermediate",
        mastered_concepts=mastered,
        weak_concepts=(),
        misconceptions=(),
        learning_goal="理解算法原理",
    )
    if spec.kind == "prerequisite":
        single_gap = StudentProfile(
            student_id=f"{task.task_id}_single_gap",
            level="intermediate",
            mastered_concepts=tuple(item for item in mastered if item != spec.value),
            weak_concepts=(spec.value,),
            misconceptions=(),
            learning_goal=spec.learning_goal,
        )
    elif spec.kind == "misconception":
        single_gap = StudentProfile(
            student_id=f"{task.task_id}_single_gap",
            level="intermediate",
            mastered_concepts=mastered,
            weak_concepts=(),
            misconceptions=(spec.value,),
            learning_goal=spec.learning_goal,
        )
    else:
        single_gap = StudentProfile(
            student_id=f"{task.task_id}_single_gap",
            level="intermediate",
            mastered_concepts=mastered,
            weak_concepts=(),
            misconceptions=(),
            learning_goal=spec.learning_goal,
        )
    return no_gap, single_gap


def wrong_gap(task: SearchTask) -> EvidenceGap:
    """Return one preregistered mismatched learner obligation for a task."""

    requirement_id = _WRONG_REQUIREMENT_IDS.get(task.task_id)
    if requirement_id is None:
        raise ValueError(f"task has no wrong-gap control: {task.task_id}")
    learner_requirement = next(
        (item for item in task.evidence_requirements if item.requirement_id == requirement_id),
        None,
    )
    if learner_requirement is None:
        raise ValueError(f"wrong-gap requirement is absent: {requirement_id}")
    core = tuple(item for item in task.evidence_requirements if item.kind == "core")
    return EvidenceGap(core_requirements=core, learner_requirements=(learner_requirement,))
