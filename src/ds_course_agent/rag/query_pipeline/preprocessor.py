"""
Query Preprocessor

负责将用户输入和上下文信息整理成标准的 QueryContext
"""

import logging
import re
import threading
from typing import Any

from ds_course_agent.rag.learner_state import LearnerStateSnapshot

from .models import DetectedConcept, QueryContext
from .utils import collect_recent_context, is_contextual_followup

logger = logging.getLogger(__name__)

_CODE_STRONG_PATTERNS = [
    r"```(?:python|py)?\s*[\s\S]+?```",
    r"\bprint\s*\(",
    r"\bimport\s+[a-zA-Z_]",
    r"\bfrom\s+[a-zA-Z_][\w.]*\s+import\b",
    r"\b(def|class|for|while|if)\s+.+:",
]

_CONCEPT_QUESTION_CUES = [
    "什么是",
    "是什么",
    "解释",
    "解析",
    "说明",
    "做什么",
    "什么意思",
    "怎么写",
    "示例",
    "为什么",
    "区别",
    "原理",
    "作用",
    "影响",
    "含义",
    "对比",
    "比较",
    "不同",
    "关系",
    "效果",
    "不收敛",
    "收敛",
    "调参",
    "超参数",
    "会不会",
    "太大",
    "太小",
    "怎么选",
    "如何选",
]

_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=]",
    flags=re.IGNORECASE,
)


def _has_strong_python_signal(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _CODE_STRONG_PATTERNS)


def _has_assignment_signal(text: str) -> bool:
    return bool(_ASSIGNMENT_RE.search(text))


def _has_concept_question_cue(compact_text: str) -> bool:
    return any(cue in compact_text for cue in _CONCEPT_QUESTION_CUES)


def _assignment_counts_as_code(text: str, compact_text: str) -> bool:
    """Return whether a bare ``name=value`` should be treated as code.

    ML students frequently ask natural-language hyperparameter questions such
    as ``alpha=0.01 为什么更好`` or ``SVM 的 C=1 和 C=10 有什么区别``.
    Those should remain course concept questions, not be executed/reviewed as
    Python.  Bare assignment is therefore only a weak code signal: it counts
    when the user explicitly frames it as code/program/script, or when there is
    no concept-question cue.
    """

    if not _has_assignment_signal(text):
        return False
    explicit_code_frame = any(cue in compact_text for cue in ["代码", "程序", "脚本", "code"])
    return explicit_code_frame or not _has_concept_question_cue(compact_text)


class QueryPreprocessor:
    """查询预处理器"""

    def __init__(self, enable_concept_detection: bool = True):
        """
        Args:
            enable_concept_detection: 是否启用概念识别（较重操作，测试时可禁用）
        """
        self.enable_concept_detection = enable_concept_detection

    def process(
        self,
        user_input: str,
        session_id: str,
        student_id: str,
        chat_history: list[Any],
        learner_state: LearnerStateSnapshot | None = None,
    ) -> QueryContext:
        """
        处理查询，生成 QueryContext

        Args:
            user_input: 用户原始输入
            session_id: 会话ID
            student_id: 学生ID
            chat_history: 对话历史
            learner_state: 当前学习状态

        Returns:
            QueryContext
        """
        # 1. 基础归一化
        normalized_query = self._normalize_query(user_input)

        # 2. 提取最近上下文
        recent_context = self._collect_recent_context(chat_history, limit=4)

        # 3. 概念识别（可选，较重）
        detected_concepts = []
        if self.enable_concept_detection:
            detected_concepts = self._detect_concepts(normalized_query, learner_state)

        # 4. 意图识别
        detected_intents = self._detect_intents(normalized_query)

        # 5. 学习信号识别
        is_clarification = self._is_clarification_signal(normalized_query)
        is_mastery = self._is_mastery_signal(normalized_query)

        # 6. Skill 候选由 QueryPipeline 的惰性 enricher 在确有需要时选择。
        skill_candidate_keys: set[str] = set()

        # 7. 判断是否是 follow-up
        is_followup = self._is_followup_question(normalized_query, chat_history)

        # 8. 路由使用的学习状态摘要
        learner_state_summary = learner_state.summary() if learner_state is not None else None

        return QueryContext(
            original_query=user_input,
            normalized_query=normalized_query,
            session_id=session_id,
            student_id=student_id,
            enriched_query=normalized_query,
            chat_history=chat_history,
            recent_context=recent_context,
            learner_state_summary=learner_state_summary,
            detected_concepts=detected_concepts,
            detected_intents=detected_intents,
            is_followup=is_followup,
            is_clarification_signal=is_clarification,
            is_mastery_signal=is_mastery,
            skill_candidate_keys=skill_candidate_keys,
        )

    def _normalize_query(self, query: str) -> str:
        """查询归一化"""
        # 基础清理
        normalized = query.strip()

        # 去除多余空白
        import re

        normalized = re.sub(r"\s+", " ", normalized)

        return normalized

    def _collect_recent_context(self, chat_history: list[Any], limit: int = 4) -> str:
        """收集最近的对话上下文"""
        return collect_recent_context(
            chat_history,
            limit=limit,
            include_roles=True,
            ai_truncate_chars=200,
        )

    def _detect_concepts(self, query: str, profile: Any | None = None) -> list[DetectedConcept]:
        """概念识别（调用现有的 knowledge mapper）。"""
        detected = []

        try:
            from ds_course_agent.rag.knowledge_mapper import map_question_to_concepts

            matches = map_question_to_concepts(query, top_k=5)
            for match in matches:
                detected.append(
                    DetectedConcept(
                        concept_id=match.concept_id,
                        method=match.method,
                        confidence=float(match.score),
                        metadata={
                            "display_name": match.display_name,
                            "chapter": match.chapter,
                        },
                    )
                )
        except Exception as e:
            logger.warning("概念识别失败: %s", e)

        return detected

    def _detect_intents(self, query: str) -> list[str]:
        """意图识别（规则 + 关键词）"""
        intents = []
        q = query.lower()

        # 时间相关
        if any(kw in q for kw in ["现在", "当前", "今天", "几点", "时间"]):
            intents.append("datetime")

        # 课程安排
        if any(kw in q for kw in ["第", "周", "课程安排", "进度", "作业", "考试"]):
            intents.append("schedule")

        # 学习路径
        if any(kw in q for kw in ["学习路线", "怎么学", "先学", "后学", "顺序"]):
            intents.append("learning_path")

        # 概念解释
        if any(kw in q for kw in ["什么是", "是什么", "定义", "含义", "解释"]):
            intents.append("concept_explanation")

        # 概念对比
        if any(kw in q for kw in ["区别", "对比", "vs", "比较", "不同"]):
            intents.append("comparison")

        # 代码请求
        if any(kw in q for kw in ["代码", "实现", "python", "怎么写", "示例"]):
            intents.append("code_request")

        # 代码审查请求：贴了代码并问"对不对/错在哪"，优先于盲执行
        if self._is_code_review_request(query):
            intents.append("code_review")

        if self._is_python_execution_request(query):
            intents.append("python_execution")

        # 应用场景
        if any(kw in q for kw in ["应用", "例子", "场景", "实际", "用途"]):
            intents.append("application")

        return intents

    def _is_python_execution_request(self, query: str) -> bool:
        """判断用户是否明确要求运行/调试一段 Python 代码。"""
        q = query.lower()
        compact = "".join(q.split())

        execution_cues = [
            "运行",
            "执行",
            "跑一下",
            "跑下",
            "算一下输出",
            "输出结果",
            "告诉我输出",
            "调试",
            "报错",
            "debug",
            "run",
            "execute",
            "python_exec_tool",
        ]
        has_execution_cue = any(cue in compact for cue in execution_cues)

        has_strong_code = _has_strong_python_signal(q)
        has_assignment_code = _assignment_counts_as_code(q, compact)
        has_code = has_strong_code or has_assignment_code

        # 整条消息本身就是简短 Python 语句时，也应直接进入执行路由。
        looks_like_standalone_code = bool(
            has_code
            and has_strong_code
            and not _has_concept_question_cue(compact)
            and len(query.strip().splitlines()) <= 8
        )

        return (has_execution_cue and has_code) or looks_like_standalone_code

    def _is_code_review_request(self, query: str) -> bool:
        """判断用户是否贴了代码并询问其正确性/错误（而非要求运行）。

        触发条件：消息中包含代码 + 审查/检查类提问，且没有明确的"运行/执行"
        意图（运行类请求交给 python_execution 路由）。

        审查/执行线索只在"问题部分"（剥离代码后）上匹配，避免学生代码注释里的
        "运行/调试"等词干扰路由。
        """
        q = query.lower()
        compact = "".join(q.split())

        has_code = _has_strong_python_signal(q) or _assignment_counts_as_code(q, compact)
        if not has_code:
            return False

        # 只在问题部分匹配线索，避免代码注释/字符串里的词误触发
        from ds_course_agent.rag.code_executor import extract_question

        question_part = extract_question(query).lower() or q

        review_cues = [
            "正确吗",
            "对吗",
            "对不对",
            "有问题吗",
            "有没有问题",
            "错在哪",
            "哪里错了",
            "哪里错",
            "哪里有问题",
            "有bug",
            "有错",
            "有问题",
            "为什么不",
            "为什么报错",
            "为什么不对",
            "怎么回事",
            "帮我看看",
            "帮我检查",
            "帮我找错",
            "检查一下",
            "review",
            "check my code",
        ]
        has_review = any(cue in question_part for cue in review_cues)

        # 明确的执行意图优先走 python_execution
        execution_cues = ["运行", "执行", "跑一下", "跑下", "调试", "debug", "run", "execute"]
        has_explicit_execution = any(cue in question_part for cue in execution_cues)

        return has_review and not has_explicit_execution

    def _is_clarification_signal(self, query: str) -> bool:
        """判断是否是澄清请求"""
        patterns = [
            "不太懂",
            "不理解",
            "不明白",
            "没懂",
            "不清楚",
            "再解释",
            "详细",
            "具体",
            "为什么",
            "怎么理解",
            "什么意思",
        ]
        q = query.lower()
        return any(p in q for p in patterns)

    def _is_mastery_signal(self, query: str) -> bool:
        """判断是否是掌握信号"""
        patterns = ["我懂了", "明白了", "理解了", "会了", "清楚了", "知道了", "学会了"]
        q = query.lower()
        return any(p in q for p in patterns)

    def _select_skill_candidates(self, query: str) -> set:
        """选择 skill 候选。

        优先复用现有 SkillLoader 的选择逻辑；如果加载失败，再使用轻量规则兜底。
        返回值使用技能目录中的 canonical key，例如：
        - learning-path
        - misconception-handling
        - personalized-explanation
        """
        try:
            from ds_course_agent.rag.skill_system import get_skill_loader

            loader = get_skill_loader()
            matches = loader.select_candidates(query)
            return {item.skill.key for item in matches}
        except Exception as e:
            logger.warning("skill 候选选择失败，使用规则兜底: %s", e)

        candidates = set()
        q = query.lower()

        if any(kw in q for kw in ["学习路线", "怎么学", "先学", "学习计划"]):
            candidates.add("learning-path")

        if any(kw in q for kw in ["不太懂", "不理解", "为什么", "错误"]):
            candidates.add("misconception-handling")

        if any(kw in q for kw in ["解释", "什么是", "是什么", "举例"]):
            candidates.add("personalized-explanation")

        return candidates

    def _is_followup_question(self, query: str, chat_history: list[Any]) -> bool:
        """判断是否是后续问题"""
        return bool(chat_history) and is_contextual_followup(query, allow_short_question=False)


_preprocessor: QueryPreprocessor | None = None
_preprocessor_lock = threading.Lock()


def get_preprocessor(enable_concept_detection: bool = True) -> QueryPreprocessor:
    """
    获取预处理器单例。

    注意：enable_concept_detection 会影响预处理行为，因此当请求的配置与
    已有单例不一致时，需要重建单例，避免测试或运行时出现隐式状态污染。
    """
    global _preprocessor
    if _preprocessor is None or _preprocessor.enable_concept_detection != enable_concept_detection:
        with _preprocessor_lock:
            if _preprocessor is None or _preprocessor.enable_concept_detection != enable_concept_detection:
                _preprocessor = QueryPreprocessor(enable_concept_detection=enable_concept_detection)
    return _preprocessor
