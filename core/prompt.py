"""Unified system prompt helpers for the teaching agent."""

from pathlib import Path

import utils.config as config
from core.skill_system import get_skill_registry


_PROMPT_DIR = Path(__file__).parent.parent / "docs" / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPT_DIR / "system_prompt.txt"


def get_system_prompt() -> str:
    """Load the base system prompt and append the skill catalog."""
    if _SYSTEM_PROMPT_PATH.exists():
        base_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    else:
        base_prompt = _get_default_prompt().strip()

    registry = get_skill_registry()
    skill_section = registry.build_skills_prompt_section().strip()
    if not skill_section:
        return base_prompt

    return f"{base_prompt}\n\n{skill_section}"


def _get_default_prompt() -> str:
    return (
        f"你是一位专业的《{config.COURSE_NAME}》课程助教。\n"
        "你的职责是帮助学生理解课程内容，回答与课程相关的问题。\n"
        "当学生提出与课程内容相关的问题时，请使用 course_rag_tool 检索课程资料并回答。\n"
        "如果问题与课程无关，请礼貌地告知学生你只能回答课程相关问题。"
    )
