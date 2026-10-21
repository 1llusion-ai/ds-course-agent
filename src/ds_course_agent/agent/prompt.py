"""Unified system prompt helpers for the teaching agent."""

import ds_course_agent.shared.config as config
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.skill_system import get_skill_registry

_PROMPT_DIR = PROJECT_ROOT / "docs" / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPT_DIR / "system_prompt.txt"


def get_system_prompt(course=None) -> str:
    """Load the base system prompt and append inline teaching skill instructions."""
    if course is not None and getattr(course, "prompt_path", ""):
        prompt_path = PROJECT_ROOT / course.prompt_path
    else:
        prompt_path = _SYSTEM_PROMPT_PATH
    if prompt_path.exists():
        base_prompt = prompt_path.read_text(encoding="utf-8").strip()
    else:
        base_prompt = _get_default_prompt().strip()

    if course is not None:
        course_name = str(getattr(course, "display_name", "")).strip()
        if course_name:
            base_prompt = base_prompt.replace("《数据科学导论》", f"《{course_name}》")
            base_prompt = base_prompt.replace("数据科学导论", course_name)
            base_prompt = base_prompt.replace("数据科学基础知识", f"{course_name}课程基础知识")

    registry = get_skill_registry()
    skill_section = registry.build_skills_prompt_section().strip()
    if not skill_section:
        return base_prompt

    return f"{base_prompt}\n\n{skill_section}"


def _get_default_prompt() -> str:
    return (
        f"你是“数字力”导学智能体，当前辅导的课程为《{config.COURSE_NAME}》。\n"
        "你的职责是帮助学生理解课程内容，回答与课程相关的问题。\n"
        "当学生明确询问课程概念、教材定义、原理或课程资料依据时，优先使用 course_rag_tool 检索课程资料并回答；"
        "当学生请求代码解析、代码示例、Python 演示或实现思路时，请自主判断是否需要检索，不要强行为了来源调用 RAG。\n"
        "如果问题与课程无关，请礼貌地告知学生你只能回答课程相关问题。"
    )
