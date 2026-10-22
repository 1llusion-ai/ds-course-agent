"""Shared resolved targets and observable author tasks for assessment stages.

The service resolves this context once per frozen course resource revision.
Authors receive slot instructions; independent reviewers see only target
identity so their observed operation cannot be anchored by the requested label.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ds_course_agent.assessment.evidence import AssessmentTarget
from ds_course_agent.assessment.models import (
    DIFFICULTY_RULES,
    CognitiveOperation,
    Difficulty,
    GenerateQuestionsRequest,
    question_slot_id,
)


@dataclass(frozen=True)
class CognitiveTaskRule:
    """Observable thinking and a counterexample, shared by author and editor."""

    required_task: str
    insufficient_task: str


COGNITIVE_TASK_RULES = {
    CognitiveOperation.RECALL: CognitiveTaskRule(
        "识别教材中的定义、性质或名称，选项需能区分相近概念。",
        "答案直接写在题干、同义反复或仅靠常识。",
    ),
    CognitiveOperation.INTERPRETATION: CognitiveTaskRule(
        "要求比较概念或条件，或解释教材支持的关系、机制差异、适用边界；选项表达完整判断及依据。",
        "只问某个定义对应哪个名称，或从定义中识别标签，属于 recall；加长情境不改变认知操作。",
    ),
    CognitiveOperation.APPLICATION: CognitiveTaskRule(
        "提供教材未逐字给出的具体实例及必要条件，要求把教材规则用于实例，判断做法、结果或方法选择。",
        "只背诵一般用途，或情境已经给出答案而无需应用规则。",
    ),
    CognitiveOperation.ANALYSIS: CognitiveTaskRule(
        "提供至少两个需要同时考虑的条件，要求组合教材规则进行多步推理或权衡；选项体现条件组合的后果。",
        "只识别一个定义、套用一个条件，或增加无关条件、术语和题干长度。",
    ),
}

DIFFICULTY_SCAFFOLDING = {
    Difficulty.BASIC: "使用熟悉情境，提供必要的操作条件，聚焦一个核心区别或一次规则应用；降低背景负担。",
    Difficulty.INTERMEDIATE: "使用新的具体情境，学生须自行选择比较维度或应用规则；不给出解题步骤。",
    Difficulty.ADVANCED: "要求整合多个条件并解释权衡或边界；干扰项针对漏用条件或错误组合规则。",
}


@dataclass(frozen=True)
class AssessmentTaskContext:
    """Server-owned request and resolved target; never accepted from HTTP clients."""

    request: GenerateQuestionsRequest
    target: AssessmentTarget

    def __post_init__(self) -> None:
        if not isinstance(self.request, GenerateQuestionsRequest) or not isinstance(self.target, AssessmentTarget):
            raise TypeError("assessment task requires a typed request and resolved target")
        if self.target.concept_id != self.request.target_kc_id:
            raise ValueError("assessment task target must match the request")

    def target_text(self) -> str:
        """Render lexical scope only, excluding answers, learner state and requested goals."""
        return json.dumps(
            {
                "kc_id": self.target.concept_id,
                "display_name": self.target.name,
                "aliases": tuple(alias for alias in self.target.aliases if alias != self.target.name),
                "chapter": self.target.chapter,
                "section": self.target.section,
                "components": [member.model_dump(mode="json") for member in self.target.components],
            },
            ensure_ascii=False,
        )

    def author_task(self, slot_index: int) -> dict[str, object]:
        """Resolve a slot's required task without relying on objective array order."""
        objective = self.request.objective_for_slot(slot_index)
        operations = (
            (objective.operation,)
            if objective
            else tuple(sorted(DIFFICULTY_RULES[self.request.difficulty].operations, key=lambda item: item.value))
        )
        return {
            "slot_id": question_slot_id(self.request.target_kc_id, slot_index),
            "slot_index": slot_index,
            "objective_kind": objective.kind.value if objective else None,
            "learning_objective": objective.objective if objective else "考查目标知识点的教材事实或规则。",
            "allowed_operations": [operation.value for operation in operations],
        }

    def learner_text(self) -> str:
        """Render only bounded relevant learning facts for the author and editor."""
        evidence = self.request.learner_evidence
        if evidence is None:
            return "未提供；缺少作答记录时不推断掌握程度。"
        return json.dumps(evidence.model_dump(mode="json", exclude_none=True), ensure_ascii=False)

    def author_text(self) -> str:
        """Render course goals and the full ordered task plan for authors and editors."""
        slots = [self.author_task(index) for index in range(self.request.count)]
        operations = sorted({operation for slot in slots for operation in slot["allowed_operations"]})
        return json.dumps(
            {
                "course_learning_objectives": self.target.learning_objectives,
                "scaffolding": DIFFICULTY_SCAFFOLDING[self.request.difficulty],
                "operation_rules": {
                    operation: {
                        "required_task": COGNITIVE_TASK_RULES[CognitiveOperation(operation)].required_task,
                        "insufficient_task": COGNITIVE_TASK_RULES[CognitiveOperation(operation)].insufficient_task,
                    }
                    for operation in operations
                },
                "slots": slots,
            },
            ensure_ascii=False,
        )
