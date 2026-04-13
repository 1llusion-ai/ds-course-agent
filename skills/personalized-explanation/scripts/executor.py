"""Personalized explanation skill executor."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import List


project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.knowledge_mapper import map_question_to_concepts
from core.memory_core import get_memory_core
from core.profile_models import StudentProfile
from core.tools import course_rag_tool


def _load_local_module(filename: str, module_suffix: str):
    module_path = Path(__file__).with_name(filename)
    module_name = f"skill_personalized_explanation_{module_suffix}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load local skill module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_strategy_module = _load_local_module("strategy.py", "strategy")
TeachingStrategy = _strategy_module.TeachingStrategy
build_strategy = _strategy_module.build_strategy
strategy_to_string = _strategy_module.strategy_to_string


def _get_llm():
    from core.agent import get_chat_model

    return get_chat_model()


def _call_llm(prompt: str) -> str:
    llm = _get_llm()
    response = llm.invoke(prompt)
    if hasattr(response, "content"):
        return response.content
    return str(response) if response else ""


def _make_concept_proxy(concept_id: str, display_name: str, chapter: str, method: str, score: float):
    class ConceptProxy:
        pass

    proxy = ConceptProxy()
    proxy.concept_id = concept_id
    proxy.display_name = display_name
    proxy.chapter = chapter
    proxy.method = method
    proxy.score = score
    return proxy


class PersonalizedExplanationSkill:
    """Generate grounded explanations with light personalization."""

    def execute(self, question: str, student_id: str, session_id: str) -> str:
        del session_id

        profile = get_memory_core().get_profile(student_id)
        matched_concepts = map_question_to_concepts(question, top_k=3)

        if not matched_concepts:
            matched_concepts = self._infer_from_profile(question, profile)

        if not matched_concepts:
            return self._fallback(question)

        strategy = build_strategy(matched_concepts, profile, question)
        knowledge = course_rag_tool.invoke(question)
        prompt = self._build_prompt(
            question=question,
            matched_concepts=matched_concepts,
            strategy=strategy,
            knowledge=knowledge,
        )
        response = _call_llm(prompt)
        scaffold = self._build_scaffold(strategy, matched_concepts)
        return self._merge_response(response, scaffold)

    def _infer_from_profile(self, question: str, profile: StudentProfile) -> List:
        inferred = []
        seen = set()

        for concept in profile.weak_spot_candidates:
            if concept.display_name and concept.display_name in question and concept.concept_id not in seen:
                inferred.append(
                    _make_concept_proxy(
                        concept_id=concept.concept_id,
                        display_name=concept.display_name,
                        chapter="",
                        method="profile_hint",
                        score=0.82,
                    )
                )
                seen.add(concept.concept_id)

        for concept in profile.recent_concepts.values():
            if concept.display_name and concept.display_name in question and concept.concept_id not in seen:
                inferred.append(
                    _make_concept_proxy(
                        concept_id=concept.concept_id,
                        display_name=concept.display_name,
                        chapter=concept.chapter,
                        method="profile_hint",
                        score=0.78,
                    )
                )
                seen.add(concept.concept_id)

        return inferred

    def _build_prompt(
        self,
        question: str,
        matched_concepts: List,
        strategy: TeachingStrategy,
        knowledge: str,
    ) -> str:
        concept_info = "\n".join(
            f"- {item.display_name}（匹配方式：{item.method}，分数：{item.score:.2f}）"
            for item in matched_concepts
        )
        relevant_known = "、".join(strategy.relevant_known_concepts) or "无"
        relevant_weak = "、".join(strategy.relevant_weak_spots) or "无"
        strategy_desc = strategy_to_string(strategy, matched_concepts)
        has_valid_knowledge = bool(knowledge and knowledge != "无相关资料" and len(knowledge) > 50)

        if has_valid_knowledge:
            return f"""你是《数据科学导论》课程的 AI 助教。请严格基于教材资料回答问题。

当前问题：
{question}

识别到的核心知识点：
{concept_info}

只在强相关时可用的历史信息：
- 强相关已学知识点：{relevant_known}
- 强相关薄弱点：{relevant_weak}

教学策略：
{strategy_desc}

教材参考资料：
{knowledge}

回答要求：
1. 严格基于教材资料，不要编造教材没有的信息。
2. 只有在“强相关”时才提及学生历史知识点或薄弱点；如果关系不强，就直接解释当前问题。
3. 不要机械提及“当前章节”“学习进度”或无关概念。
4. 如果存在强相关薄弱点，要用更直观的解释，并点清它和当前知识点的区别。
5. 如果存在强相关已学知识点，可以用它做桥接，但只保留最必要的 1-2 个。
6. 先讲核心直觉，再讲关键概念/公式，最后补一句怎么继续学。
"""

        return f"""你是《数据科学导论》课程的 AI 助教。

当前问题：
{question}

情况说明：
课程资料中暂时没有找到足够直接的相关内容。

回答要求：
1. 诚实告诉学生教材中没有找到足够信息。
2. 如果问题可能是术语换了一种说法，可以提醒学生换关键词重问。
3. 不要为了个性化而强行关联无关知识点。
"""

    def _build_scaffold(self, strategy: TeachingStrategy, matched_concepts: List) -> str:
        if not matched_concepts:
            return ""

        target = matched_concepts[0].display_name

        if strategy.relevant_weak_spots:
            weak = "、".join(strategy.relevant_weak_spots[:2])
            return (
                f"考虑到你之前在 {weak} 上还有点容易混淆，这次我会重点把 {target} 讲清楚。"
                "我会先讲核心直觉，再用一个小例子帮你抓住区别。"
            )

        if strategy.relevant_known_concepts:
            related = "、".join(strategy.relevant_known_concepts[:2])
            return (
                f"这次我会把 {target} 和你之前学过的 {related} 连起来讲。"
                "我会先讲核心直觉，再展开关键点。"
            )

        return ""

    def _merge_response(self, content: str, scaffold: str) -> str:
        if not scaffold:
            return content
        if content.strip().startswith(scaffold[:12]):
            return content
        return f"{scaffold}\n\n{content}"

    def _fallback(self, question: str) -> str:
        try:
            knowledge = course_rag_tool.invoke(question)
            if knowledge and knowledge != "无相关资料" and len(knowledge) > 50:
                return f"根据课程资料，我先给你一版基础说明：\n\n{knowledge}"
            return (
                "抱歉，我暂时没有在课程资料里找到足够直接的内容。"
                "你可以换一个更具体的课程术语再问我，比如直接说 PCA、SVM、过拟合、交叉验证。"
            )
        except Exception as exc:
            return f"抱歉，检索课程资料时出了点问题，请稍后重试。({str(exc)[:80]})"


def explain(question: str, student_id: str, session_id: str) -> str:
    return PersonalizedExplanationSkill().execute(question, student_id, session_id)


def execute(question: str, student_id: str, session_id: str) -> str:
    """Claude-style skill entrypoint."""
    return explain(question, student_id, session_id)
