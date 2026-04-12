"""教学策略构建规则"""
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class TeachingStrategy:
    """教学策略"""
    target_concepts: List[str]
    emphasize_weak_spots: List[str]
    connect_to_known: List[str]
    suggest_examples: bool
    reminder_chapter: Optional[str] = None


def build_strategy(matched_concepts: list, profile, question: str) -> TeachingStrategy:
    """根据画像和知识点构建教学策略"""
    target_concepts = [m.concept_id for m in matched_concepts]
    emphasize_weak_spots = []
    connect_to_known = []
    suggest_examples = False
    reminder_chapter = None

    # 检查薄弱点
    for match in matched_concepts:
        weak_spot = profile.get_weak_spot(match.concept_id)
        if weak_spot and weak_spot.confidence > 0.6:
            emphasize_weak_spots.append(match.concept_id)
            suggest_examples = True

    # 关联已学概念
    for concept_id, concept in profile.recent_concepts.items():
        if concept_id in target_concepts:
            continue
        if concept.mention_count >= 2:
            connect_to_known.append(concept_id)

    # 检查跳章
    current_chapter = profile.progress.current_chapter
    if matched_concepts and current_chapter:
        primary_chapter = matched_concepts[0].chapter
        if primary_chapter and primary_chapter != current_chapter:
            try:
                current_num = int(current_chapter.replace("第", "").replace("章", ""))
                primary_num = int(primary_chapter.replace("第", "").replace("章", ""))
                if primary_num > current_num + 1:
                    reminder_chapter = current_chapter
            except (ValueError, AttributeError):
                pass

    return TeachingStrategy(
        target_concepts=target_concepts,
        emphasize_weak_spots=list(dict.fromkeys(emphasize_weak_spots)),
        connect_to_known=list(dict.fromkeys(connect_to_known)),
        suggest_examples=suggest_examples,
        reminder_chapter=reminder_chapter
    )


def strategy_to_string(strategy: TeachingStrategy, matched_concepts: list) -> str:
    """将策略转为字符串描述"""
    parts = []

    if strategy.emphasize_weak_spots:
        weak_names = [
            m.display_name for m in matched_concepts
            if m.concept_id in strategy.emphasize_weak_spots
        ]
        if weak_names:
            parts.append(f"学生之前对[{', '.join(weak_names)}]有困惑，需要重点解释")

    if strategy.connect_to_known:
        parts.append("可以关联学生已熟悉的概念进行类比")

    if strategy.suggest_examples:
        parts.append("建议提供具体示例帮助理解")

    if strategy.reminder_chapter:
        parts.append(f"学生当前进度在{strategy.reminder_chapter}，可提醒关联")

    return "；".join(parts) if parts else "标准讲解"
