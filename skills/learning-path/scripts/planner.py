"""Rule-based planner for learning path recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence


@dataclass
class RouteStep:
    title: str
    details: List[str] = field(default_factory=list)


@dataclass
class LearningPathPlan:
    summary: str
    current_chapter: str | None
    recent_focuses: List[str] = field(default_factory=list)
    weak_spots: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    priorities: List[str] = field(default_factory=list)
    steps: List[RouteStep] = field(default_factory=list)
    quick_actions: List[str] = field(default_factory=list)
    checkpoints: List[str] = field(default_factory=list)


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _chapter_number(chapter: str | None) -> int | None:
    if not chapter:
        return None
    match = re.search(r"第\s*(\d+)\s*章", chapter)
    if not match:
        return None
    return int(match.group(1))


def _pick_recent_focuses(profile, limit: int = 3) -> List[str]:
    concepts = sorted(
        profile.recent_concepts.values(),
        key=lambda item: (item.last_mentioned_at or 0, item.mention_count),
        reverse=True,
    )
    return [item.display_name for item in concepts[:limit] if item.display_name]


def _pick_active_weak_spots(profile, limit: int = 3) -> List[str]:
    spots = sorted(
        profile.weak_spot_candidates,
        key=lambda item: (item.confidence, item.last_triggered_at or 0),
        reverse=True,
    )
    return [item.display_name for item in spots[:limit] if item.display_name]


def _target_names(matched_concepts: Sequence) -> List[str]:
    return _dedupe_keep_order(
        getattr(item, "display_name", "")
        for item in list(matched_concepts)[:2]
    )


def _find_concept_by_display_name(mapper, display_name: str):
    for concept in mapper.graph.concepts.values():
        if concept.get("display_name") == display_name:
            return concept
    return None


def _related_concepts(mapper, matched_concepts: Sequence, limit: int = 4) -> List[dict]:
    related: List[dict] = []
    blocked = set(_target_names(matched_concepts))

    for concept in list(matched_concepts)[:2]:
        for display_name in mapper.get_related_concepts(getattr(concept, "concept_id", "")):
            if not display_name or display_name in blocked:
                continue
            concept_data = _find_concept_by_display_name(mapper, display_name)
            related.append(
                {
                    "display_name": display_name,
                    "chapter": (concept_data or {}).get("chapter"),
                }
            )

    unique: List[dict] = []
    seen = set()
    for item in related:
        key = item["display_name"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:limit]


def build_learning_path_plan(question: str, matched_concepts: Sequence, profile, mapper) -> LearningPathPlan:
    del question

    recent_focuses = _pick_recent_focuses(profile)
    weak_spots = _pick_active_weak_spots(profile)
    targets = _target_names(matched_concepts)
    current_chapter = profile.progress.current_chapter or None
    related = _related_concepts(mapper, matched_concepts)

    primary_target_chapter = _chapter_number(getattr(matched_concepts[0], "chapter", None)) if matched_concepts else None
    prerequisites = []
    extensions = []
    for item in related:
        item_chapter_num = _chapter_number(item.get("chapter"))
        if primary_target_chapter is not None and item_chapter_num is not None and item_chapter_num <= primary_target_chapter:
            prerequisites.append(item["display_name"])
        else:
            extensions.append(item["display_name"])

    weak_priority = [name for name in weak_spots if name in targets or name in prerequisites or name in extensions]
    priorities: List[str] = []
    for name in weak_priority[:2]:
        priorities.append(f"优先补薄弱点：{name}")
    for name in prerequisites[:2]:
        priorities.append(f"前置/关联知识：{name}")
    for name in targets[:2]:
        priorities.append(f"核心目标：{name}")
    for name in extensions[:2]:
        priorities.append(f"延伸对比：{name}")
    priorities = _dedupe_keep_order(priorities)

    if targets:
        summary = "建议按“薄弱点/前置概念 -> 核心目标 -> 对比延伸”的顺序推进。"
    elif weak_spots:
        summary = "建议先收敛薄弱点，再按章节顺序往后推进。"
    else:
        summary = "建议先搭框架，再抓重点，最后做自测巩固。"

    if targets:
        primary_target = targets[0]
        step1_details = []
        if weak_priority:
            step1_details.append(f"先把和这次主题强相关的薄弱点 {', '.join(weak_priority[:2])} 处理掉，避免边学边混。")
        if prerequisites:
            step1_details.append(f"再回顾 {', '.join(prerequisites[:2])}，把前置和关联概念串起来。")
        if not step1_details:
            step1_details.append(f"先明确 {primary_target} 解决什么问题、为什么需要它。")

        step2_details = [
            f"再集中学习 {primary_target} 的核心定义、关键直觉和典型使用场景。"
        ]
        if len(targets) > 1:
            step2_details.append(f"如果时间够，再把 {targets[1]} 一起纳入主线，避免只学到一半。")

        step3_details = []
        if extensions:
            step3_details.append(f"最后把 {primary_target} 和 {', '.join(extensions[:2])} 做对比，检查自己是否真的分清。")
        else:
            step3_details.append(f"最后用一个小例子或一道小题检验自己是否真的理解了 {primary_target}。")
    else:
        step1_details = [
            "先按薄弱程度找出最需要先补的 1-2 个概念，不要同时摊太多。"
        ]
        if weak_spots:
            step1_details.append(f"当前优先考虑：{', '.join(weak_spots[:2])}。")

        step2_details = [
            "再按章节顺序把相关知识点串起来，先补前面基础，再看后面内容。"
        ]
        if current_chapter:
            step2_details.append(f"你现在可以把 {current_chapter} 当作主线参考。")

        step3_details = [
            "最后做一轮自测：能否复述定义、说清区别、举出一个例子。"
        ]

    steps = [
        RouteStep("先定优先级", step1_details),
        RouteStep("再学核心内容", step2_details),
        RouteStep("最后做辨析和巩固", step3_details),
    ]

    quick_actions = []
    if priorities:
        quick_actions.append(f"先花 10 分钟处理第一优先级：{priorities[0].split('：', 1)[-1]}。")
    if targets:
        quick_actions.append(f"再花 15 分钟专注理解 {targets[0]} 的核心定义和直觉。")
    else:
        quick_actions.append("再花 15 分钟按章节顺序串联相关概念。")
    quick_actions.append("最后留 5 到 10 分钟做口头复述或小题自测。")

    checkpoints = []
    if targets:
        checkpoints.append(f"你能不能不用教材原句，自己解释清楚 {targets[0]}。")
        checkpoints.append(f"你能不能说出 {targets[0]} 和相近概念的区别。")
    else:
        checkpoints.append("你能不能说出自己当前最卡的是定义、区别，还是应用。")
    if weak_priority:
        checkpoints.append(f"你能不能把 {weak_priority[0]} 相关困惑讲清楚，而不是只停留在“感觉懂了”。")

    return LearningPathPlan(
        summary=summary,
        current_chapter=current_chapter,
        recent_focuses=recent_focuses,
        weak_spots=weak_spots,
        targets=targets,
        priorities=priorities,
        steps=steps,
        quick_actions=quick_actions,
        checkpoints=checkpoints,
    )
