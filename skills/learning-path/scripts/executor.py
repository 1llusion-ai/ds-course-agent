"""Learning path recommendation skill."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.knowledge_mapper import get_knowledge_mapper, map_question_to_concepts
from core.memory_core import get_memory_core


def _load_local_module(filename: str, module_suffix: str):
    module_path = Path(__file__).with_name(filename)
    module_name = f"skill_learning_path_{module_suffix}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load local skill module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_planner_module = _load_local_module("planner.py", "planner")
LearningPathPlan = _planner_module.LearningPathPlan
build_learning_path_plan = _planner_module.build_learning_path_plan


class LearningPathSkill:
    """Generate actionable learning paths for course questions."""

    def execute(self, question: str, student_id: str, session_id: str) -> str:
        del session_id

        profile = get_memory_core().get_profile(student_id)
        matched_concepts = map_question_to_concepts(question, top_k=3)
        mapper = get_knowledge_mapper()

        plan = build_learning_path_plan(
            question=question,
            matched_concepts=matched_concepts,
            profile=profile,
            mapper=mapper,
        )
        return self._render_plan(plan)

    def _render_plan(self, plan: LearningPathPlan) -> str:
        lines = [f"结合你现在的学习状态，{plan.summary}"]

        overview = []
        if plan.current_chapter:
            overview.append(f"当前章节参考：{plan.current_chapter}")
        if plan.targets:
            overview.append(f"这次的核心目标：{'、'.join(plan.targets)}")
        if plan.weak_spots:
            overview.append(f"当前薄弱点：{'、'.join(plan.weak_spots)}")
        elif plan.recent_focuses:
            overview.append(f"最近关注：{'、'.join(plan.recent_focuses)}")

        if overview:
            lines.append("")
            lines.append("先看一下当前起点：")
            for item in overview:
                lines.append(f"- {item}")

        if plan.priorities:
            lines.append("")
            lines.append("建议优先级：")
            for index, item in enumerate(plan.priorities, start=1):
                lines.append(f"{index}. {item}")

        lines.append("")
        lines.append("推荐路线：")
        for index, step in enumerate(plan.steps, start=1):
            lines.append(f"{index}. {step.title}")
            for detail in step.details:
                lines.append(f"- {detail}")

        if plan.quick_actions:
            lines.append("")
            lines.append("如果你这次只想先学 30 分钟：")
            for item in plan.quick_actions:
                lines.append(f"- {item}")

        if plan.checkpoints:
            lines.append("")
            lines.append("学完后可以这样自测：")
            for item in plan.checkpoints:
                lines.append(f"- {item}")

        return "\n".join(lines).strip()


def recommend_learning_path(question: str, student_id: str, session_id: str) -> str:
    return LearningPathSkill().execute(question, student_id, session_id)


def execute(question: str, student_id: str, session_id: str) -> str:
    """Claude-style skill entrypoint."""
    return recommend_learning_path(question, student_id, session_id)
