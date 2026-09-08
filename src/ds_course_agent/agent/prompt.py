"""Unified system prompt helpers for the teaching agent."""

import ds_course_agent.shared.config as config
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.skill_system import get_skill_registry

_PROMPT_DIR = PROJECT_ROOT / "docs" / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPT_DIR / "system_prompt.txt"


def get_system_prompt() -> str:
    """Load the base system prompt and append inline teaching skill instructions."""
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
        "当学生明确询问课程概念、教材定义、原理或课程资料依据时，优先使用 course_rag_tool 检索课程资料并回答；"
        "当学生请求代码解析、代码示例、Python 演示或实现思路时，请自主判断是否需要检索，不要强行为了来源调用 RAG。\n"
        "如果问题与课程无关，请礼貌地告知学生你只能回答课程相关问题。"
    )
