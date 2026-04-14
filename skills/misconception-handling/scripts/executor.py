"""Misconception handling skill executor.

Responsibilities:
- Classify user input (A: normal question, B: tentative wrong, C: explicit misconception)
- Retrieve evidence via course_rag_tool
- Write to profile via record_misconception_event tool
- Generate single-shot final answer
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.knowledge_mapper import map_question_to_concepts
from core.tools import course_rag_tool, record_misconception_event


# ---- LLM helpers ----

def _get_llm():
    from core.agent import get_chat_model
    return get_chat_model()


def _call_llm(prompt: str) -> str:
    llm = _get_llm()
    response = llm.invoke(prompt)
    if hasattr(response, "content"):
        return response.content
    return str(response) if response else ""


# ---- Internal misconception detector (NOT a public tool) ----

def _build_classification_prompt(user_question: str, matched_concepts: list) -> str:
    concept_info = ""
    if matched_concepts:
        lines = []
        for c in matched_concepts[:3]:
            lines.append(
                f"- 知识点：{getattr(c, 'display_name', getattr(c, 'concept_id', 'unknown'))}"
                f"（章节：{getattr(c, 'chapter', 'unknown')}）"
            )
        concept_info = "\n".join(lines)
    else:
        concept_info = "（无匹配知识点）"

    return f"""你是《数据科学导论》课程的助教，负责判断学生是否存在错误认知。

学生问题：{user_question}

涉及知识点：
{concept_info}

请根据以下标准，对学生的问题进行三分类：

A. 正常疑问 — 学生只是在正常询问，没有错误前提。
   例子："PCA是什么？" "神经网络为什么会过拟合？"

B. 试探性错误假设 — 学生带有不确定性、确认式或试探性的错误猜测，语气犹豫、不确定。
   例子："kNN不是无监督算法吗？" "PCA应该算监督学习吧？" "我以为正则化就是降维？"

C. 明确错误认知 — 学生明确断言一个错误概念，语气肯定，或者重复犯同一类错误。
   例子："kNN就是无监督算法。" "LDA是无监督算法啊。" "正则化和降维是一个东西。" "过拟合说明模型很强。"

补充规则：若学生是陈述句（例如“X是Y啊/呀/呢”）且核心命题错误，应判为 C，而不是 A。

请严格按以下JSON格式输出，只输出JSON，不要有其他内容：
{{
  "classification": "A"或"B"或"C",
  "misconception_text": "如果A类则填空字符串，B/C类填学生错误认知的核心表述",
  "correct_answer": "如果A类则填空字符串，B/C类填一句话正确答案",
  "severity": "low"（B类用）或"medium"（B-C过渡）或"high"（C类用）
}}"""


def _parse_classification_result(raw: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, return default A if parse fails."""
    try:
        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if not match:
            return _default_a()
        data = json.loads(match.group())
        classification = data.get("classification", "A")
        if classification not in ("A", "B", "C"):
            return _default_a()
        return {
            "classification": classification,
            "misconception_text": data.get("misconception_text", ""),
            "correct_answer": data.get("correct_answer", ""),
            "severity": data.get("severity", "low"),
        }
    except Exception:
        return _default_a()


def _default_a() -> Dict[str, Any]:
    return {
        "classification": "A",
        "misconception_text": "",
        "correct_answer": "",
        "severity": "low",
    }


_QUESTION_CUES = [
    "什么",
    "怎么",
    "如何",
    "为何",
    "为什么",
    "哪些",
    "多少",
    "区别",
    "对比",
    "举例",
    "解释",
    "介绍",
    "请问",
]

_MISCONCEPTION_STYLE_CUES = [
    "不是",
    "难道不是",
    "我以为",
    "我觉得是",
    "我认为",
    "我感觉",
    "一直以为",
    "应该是",
    "不该是",
    "应该算",
    "就是",
    "属于",
    "归为",
    "归到",
    "算作",
    "算是",
    "等于",
    "意味着",
    "本质上",
]


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", "", (question or "").lower())


def _quick_classify(user_question: str) -> Optional[Dict[str, Any]]:
    """Cheap fast-path to avoid LLM classification for obvious normal questions."""
    normalized = _normalize_question(user_question)
    if not normalized:
        return _default_a()

    has_question_mark = ("?" in user_question) or ("？" in user_question)
    has_question_cue = any(cue in normalized for cue in _QUESTION_CUES)
    has_misconception_style = any(cue in normalized for cue in _MISCONCEPTION_STYLE_CUES)

    if has_question_mark and not has_misconception_style:
        return _default_a()
    if has_question_cue and not has_misconception_style:
        return _default_a()
    return None


def misconception_detector(user_question: str, matched_concepts: list) -> Dict[str, Any]:
    """Internal LLM step — not a public tool."""
    quick = _quick_classify(user_question)
    if quick is not None:
        return quick
    prompt = _build_classification_prompt(user_question, matched_concepts)
    raw = _call_llm(prompt)
    return _parse_classification_result(raw)


# ---- Answer generators ----

def _generate_normal_answer(user_question: str, knowledge: str) -> str:
    if knowledge and knowledge != "无相关资料" and len(knowledge) > 30:
        return f"{knowledge}"
    prompt = f"""你是《数据科学导论》课程的AI助教。请回答学生的问题。

学生问题：{user_question}

回答要求：直接、清晰地解释课程知识点，严格基于教材内容。"""
    return _call_llm(prompt).strip()


def _generate_gentle_correction_answer(
    user_question: str,
    misconception_text: str,
    correct_answer: str,
    evidence: str,
) -> str:
    prompt = f"""你是《数据科学导论》课程的AI助教。学生提出了一个带有试探性错误假设的问题，请温和地纠正并解释。

学生问题：{user_question}

学生可能的误解：{misconception_text}
更准确的理解：{correct_answer}

教材参考：
{evidence if evidence and evidence != "无相关资料" else "（暂无直接教材依据，请基于知识点推理）"}

要求：
1. 先用一句友好的话指出容易混淆的点（例如："这里有个容易混淆的小点"）
2. 然后给出正确理解
3. 再展开解释
4. 语气温和，避免"你错了"这样的强否定
5. 严格基于教材内容或合理解释"""
    return _call_llm(prompt).strip()


def _generate_direct_correction_answer(
    user_question: str,
    misconception_text: str,
    correct_answer: str,
    evidence: str,
) -> str:
    prompt = f"""你是《数据科学导论》课程的AI助教。学生明确表达了一个错误认知，请直接纠正并解释。

学生问题：{user_question}

学生的错误认知：{misconception_text}
正确答案：{correct_answer}

教材参考：
{evidence if evidence and evidence != "无相关资料" else "（暂无直接教材依据，请基于知识点推理）"}

要求：
1. 先明确指出这个说法不对
2. 再给出正确答案
3. 然后展开解释
4. 可以稍微直接一点，但保持教学友好
5. 严格基于教材内容或合理解释"""
    return _call_llm(prompt).strip()


# ---- Record helper ----

def _call_record_event(
    session_id: str,
    student_id: str,
    concept_id: str,
    misconception_text: str,
    correct_answer: str,
    misconception_type: str,
    severity: str,
    source_evidence: str,
    raw_user_question: str,
    turn_id: str,
    target_bucket: str,
) -> None:
    """Call record_misconception_event tool, swallow errors."""
    try:
        result = record_misconception_event.invoke({
            "session_id": session_id,
            "student_id": student_id,
            "concept_id": concept_id,
            "misconception_text": misconception_text,
            "correct_answer": correct_answer,
            "misconception_type": misconception_type,
            "severity": severity,
            "source_evidence": source_evidence,
            "raw_user_question": raw_user_question,
            "turn_id": turn_id,
            "target_bucket": target_bucket,
        })
        # Log result for debugging
        import logging
        logging.debug(f"[Misconception] recorded: {result}")
    except Exception as exc:
        import logging
        logging.warning(f"[Misconception] record failed: {exc}")


# ---- Main executor ----

def execute(
    user_question: str,
    student_id: str,
    session_id: str,
    turn_id: str = "0",
) -> str:
    """
    Main entrypoint for misconception-handling skill.

    Args:
        user_question: 学生的问题
        student_id: 学生 ID
        session_id: 会话 ID
        turn_id: 对话轮次（用于画像追溯）
    """
    # Step 1: 获取概念候选
    matched_concepts = map_question_to_concepts(user_question, top_k=3)

    # Step 2: 内部 LLM 分类
    result = misconception_detector(user_question, matched_concepts)
    classification = result["classification"]
    misconception_text = result["misconception_text"]
    correct_answer = result["correct_answer"]
    severity = result["severity"]

    # Branch A: 正常疑问
    if classification == "A":
        knowledge = ""
        try:
            knowledge = course_rag_tool.invoke(user_question) or ""
        except Exception:
            pass
        return _generate_normal_answer(user_question, knowledge)

    # Step 3: B/C 分支都需要取证据
    try:
        rag_result = course_rag_tool.invoke(user_question) or ""
    except Exception:
        rag_result = ""

    # 从 RAG 结果中提取 concept_id（取第一个匹配的概念）
    concept_id = "unknown"
    if matched_concepts:
        concept_id = getattr(matched_concepts[0], "concept_id", "unknown")

    source_evidence = rag_result if rag_result else ""

    # Branch B: 试探性错误假设
    if classification == "B":
        answer = _generate_gentle_correction_answer(
            user_question=user_question,
            misconception_text=misconception_text,
            correct_answer=correct_answer,
            evidence=source_evidence,
        )
        _call_record_event(
            session_id=session_id,
            student_id=student_id,
            concept_id=concept_id,
            misconception_text=misconception_text,
            correct_answer=correct_answer,
            misconception_type="B",
            severity=severity,
            source_evidence=source_evidence[:500] if source_evidence else "",
            raw_user_question=user_question,
            turn_id=turn_id,
            target_bucket="pending_weakness",
        )
        return answer

    # Branch C: 明确错误认知
    answer = _generate_direct_correction_answer(
        user_question=user_question,
        misconception_text=misconception_text,
        correct_answer=correct_answer,
        evidence=source_evidence,
    )
    _call_record_event(
        session_id=session_id,
        student_id=student_id,
        concept_id=concept_id,
        misconception_text=misconception_text,
        correct_answer=correct_answer,
        misconception_type="C",
        severity=severity,
        source_evidence=source_evidence[:500] if source_evidence else "",
        raw_user_question=user_question,
        turn_id=turn_id,
        target_bucket="weakness",
    )
    return answer


def handle(user_question: str, student_id: str, session_id: str, turn_id: str = "0") -> str:
    """Alias for execute."""
    return execute(user_question, student_id, session_id, turn_id)
