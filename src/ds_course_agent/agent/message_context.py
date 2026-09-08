"""Render teaching state into turn-level model context."""

from __future__ import annotations

from ds_course_agent.agent.routing import RouteState
from ds_course_agent.teaching.learner_state import LearnerStateSnapshot


def format_learner_state_for_prompt(learner_state: LearnerStateSnapshot | None) -> str:
    """Render a compact natural-language learner state for model context."""

    if learner_state is None:
        return ""

    lines: list[str] = []
    progress = learner_state.progress
    if progress.current_chapter:
        lines.append(f"当前学习进度：{progress.current_chapter}")
    if progress.covered_chapters:
        lines.append("已覆盖章节：" + "、".join(map(str, progress.covered_chapters[:6])))

    recent_concepts = sorted(
        learner_state.recent_concepts.values(),
        key=lambda item: item.last_mentioned_at or 0,
        reverse=True,
    )
    if recent_concepts:
        labels: list[str] = []
        for item in recent_concepts[:5]:
            label = item.display_name or item.concept_id
            if item.chapter:
                label += f"（{item.chapter}）"
            if item.mention_count:
                label += f"x{item.mention_count}"
            labels.append(label)
        lines.append("最近关注概念：" + "、".join(labels))

    if learner_state.weak_spot_candidates:
        labels = [item.display_name or item.concept_id for item in learner_state.weak_spot_candidates[:5]]
        lines.append("当前薄弱点：" + "、".join(filter(None, labels)))
    if learner_state.pending_weak_spots:
        labels = [item.display_name or item.concept_id for item in learner_state.pending_weak_spots[:5]]
        lines.append("待观察薄弱点：" + "、".join(filter(None, labels)))

    if not lines:
        return ""
    return (
        "# Learner State Context\n"
        "以下是学生当前学习状态摘要，只用于调整讲解粒度和例子选择，不要逐字暴露内部标签：\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def build_turn_system_context(route_state: RouteState) -> str:
    """Build the per-turn system context used by model-backed routes."""

    sections: list[str] = []
    learner_state_summary = format_learner_state_for_prompt(route_state.learner_state)
    if learner_state_summary:
        sections.append(learner_state_summary)

    skill_keys = sorted(route_state.skill_candidate_keys or [])
    if skill_keys:
        sections.append(
            "# Matched Teaching Skill Hints\n"
            "The router/keyword matcher found these potentially relevant skills for this turn: "
            + ", ".join(skill_keys)
            + ". Use the inline SKILL.md instructions in the main system prompt when appropriate."
        )

    concept_labels: list[str] = []
    for item in (route_state.matched_concepts or [])[:5]:
        display_name = getattr(item, "display_name", None) or getattr(item, "concept_id", "")
        chapter = getattr(item, "chapter", "")
        if display_name and chapter:
            concept_labels.append(f"{display_name}（{chapter}）")
        elif display_name:
            concept_labels.append(str(display_name))
    if concept_labels:
        sections.append("# Current Turn Concepts\n" + "、".join(concept_labels))

    return "\n\n".join(sections)
