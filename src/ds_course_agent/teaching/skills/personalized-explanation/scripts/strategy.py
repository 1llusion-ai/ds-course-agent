"""Planning rules for personalized explanations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ds_course_agent.teaching.learner_state import (
    LearnerStateSnapshot,
    rank_active_weak_spots,
    rank_recent_concepts,
)


@dataclass
class TeachingStrategy:
    target_concepts: list[str] = field(default_factory=list)
    relevant_weak_spots: list[str] = field(default_factory=list)
    relevant_known_concepts: list[str] = field(default_factory=list)
    suggest_examples: bool = False


def _dedupe_keep_order(items: Sequence[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_strategy(
    matched_concepts: list[Any],
    learner_state: LearnerStateSnapshot,
    question: str,
) -> TeachingStrategy:
    """Build a focused teaching strategy for the current question."""
    del question

    if not matched_concepts:
        return TeachingStrategy()

    from ds_course_agent.teaching.knowledge_mapper import get_knowledge_mapper

    mapper = get_knowledge_mapper()
    target_ids = [item.concept_id for item in matched_concepts]
    related_names: list[str] = []

    for concept in matched_concepts[:2]:
        related_names.extend(mapper.get_related_concepts(concept.concept_id))

    related_name_set = set(_dedupe_keep_order(related_names))

    recent_concepts = rank_recent_concepts(learner_state)
    relevant_known = [
        item.display_name
        for item in recent_concepts
        if item.concept_id not in target_ids and item.display_name in related_name_set
    ]

    weak_spots = rank_active_weak_spots(learner_state)
    relevant_weak = [
        item.display_name
        for item in weak_spots
        if item.concept_id in target_ids or item.display_name in related_name_set
    ]

    return TeachingStrategy(
        target_concepts=_dedupe_keep_order(target_ids),
        relevant_weak_spots=_dedupe_keep_order(relevant_weak)[:2],
        relevant_known_concepts=_dedupe_keep_order(relevant_known)[:2],
        suggest_examples=bool(relevant_weak),
    )


def strategy_to_string(strategy: TeachingStrategy, matched_concepts: list) -> str:
    """Render strategy into a short natural-language summary for prompting."""
    parts: list[str] = []

    if strategy.relevant_weak_spots:
        parts.append(f"学生在 {', '.join(strategy.relevant_weak_spots)} 上还有明显困惑，解释时要更直观，并强调区别。")

    if strategy.relevant_known_concepts:
        parts.append(f"可以只关联这些强相关旧知识点：{', '.join(strategy.relevant_known_concepts)}。")

    if strategy.suggest_examples:
        parts.append("建议加入一个小例子或对比例子，帮助学生真正分清概念。")

    if not parts and matched_concepts:
        parts.append(f"重点讲清 {matched_concepts[0].display_name} 的核心直觉、定义和使用场景。")

    return " ".join(parts)
