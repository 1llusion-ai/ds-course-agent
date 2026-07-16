"""
Query Router

负责根据 QueryContext 决定路由策略
"""
import logging
import re
from typing import Optional
from .models import QueryContext, RouteDecision, RouteType
from .preprocessor import _assignment_counts_as_code, _has_concept_question_cue, _has_strong_python_signal
from .utils import is_datetime_request, is_judgement_question, is_schedule_request, normalize_query_text

logger = logging.getLogger(__name__)


class QueryRouter:
    """查询路由器"""

    def __init__(self):
        pass

    def _normalize(self, query: str) -> str:
        """与 query_pipeline.utils.normalize_query_text 保持一致的路由归一化。

        中文用户输入中常见有被输入法插入的空格；旧逻辑会去除所有空白，
        Router 也必须保持一致，否则会出现静默路由漂移。
        """
        return normalize_query_text(query)

    def route(self, context: QueryContext) -> RouteDecision:
        """
        根据 QueryContext 进行路由决策

        优先级顺序：
        1. 系统工具类（时间、课程安排）
        2. 明确教学策略类（学习路径、错误理解、个性化解释）
        3. 课程知识问答类（grounded RAG）
        4. 通用 agent fallback

        Args:
            context: 查询上下文

        Returns:
            RouteDecision
        """
        query = self._normalize(context.normalized_query)

        # 0. 代码审查请求：贴了代码并问"对不对/错在哪" → 走 code-review skill，
        #    定位错误并给出修正代码，而不是盲目执行。优先于 PYTHON_EXEC。
        if "code_review" in context.detected_intents:
            return RouteDecision(
                route=RouteType.CODE_REVIEW,
                confidence=0.93,
                reasons=["检测到代码审查请求"],
                skill_name="code-review",
                retrieval_policy="disabled",
            )

        # 1. 明确 Python 代码执行请求：直接走运行时工具，不查教材、不附来源。
        # 放在系统工具前，避免代码字符串里的“今天/第3周”等词误触发时间/课表。
        if "python_execution" in context.detected_intents:
            return RouteDecision(
                route=RouteType.PYTHON_EXEC,
                confidence=0.95,
                reasons=["检测到明确 Python 代码执行请求"],
                required_tools=["python_exec_tool"],
                retrieval_policy="disabled",
            )

        # 2. 系统工具类
        if self._is_datetime_request(query):
            return RouteDecision(
                route=RouteType.CURRENT_DATETIME,
                confidence=0.95,
                reasons=["检测到时间查询关键词"],
                required_tools=["current_datetime_tool"],
                retrieval_policy="disabled",
            )

        if self._is_schedule_request(query):
            return RouteDecision(
                route=RouteType.COURSE_SCHEDULE,
                confidence=0.95,
                reasons=["检测到课程安排查询关键词"],
                required_tools=["course_schedule_tool"],
                retrieval_policy="optional",
            )

        # 3. 高置信误认知信号仍然优先进入教学策略。
        #
        # 代码/示例类请求默认交给 agent 自主选工具，但明确带有“我以为/难道不是/
        # 应该是”等错误前提时，misconception skill 是更合适的教学路径。
        # code_review / python_exec 已在更高优先级拦截，所以这里不会抢走明确
        # 的运行或审查请求。
        if self._should_use_misconception_skill(context) and self._has_explicit_misconception_signal(context):
            return RouteDecision(
                route=RouteType.MISCONCEPTION_SKILL,
                confidence=0.89,
                reasons=self._get_misconception_reasons(context) + ["明确误认知信号优先于 autonomous tool choice"],
                skill_name="misconception-handling",
                retrieval_policy="required",
                fallback_route=RouteType.GROUNDED_RAG,
            )

        # 4. 模糊/代码类请求：交给通用 agent 自主选择工具。
        #
        # 这是借鉴 nanobot 的关键边界：Router 只抢占高置信、低歧义路径；
        # 带代码/示例/实现意图的请求即使命中课程概念，也不应被直接强制
        # grounded RAG。让 tool-capable agent 根据上下文决定是否需要查教材、
        # 审查代码、运行 Python，或直接解释。
        autonomous_decision = self._route_autonomous_tool_choice(context)
        if autonomous_decision is not None:
            return autonomous_decision

        # 5. 教学策略类

        # 5.1 学习路径 skill
        if self._should_use_learning_path_skill(context):
            return RouteDecision(
                route=RouteType.LEARNING_PATH_SKILL,
                confidence=0.90,
                reasons=self._get_learning_path_reasons(context),
                skill_name="learning-path",
                retrieval_policy="optional",
                fallback_route=RouteType.GROUNDED_RAG,
            )

        # 5.2 错误理解 / misconception skill
        if self._should_use_misconception_skill(context):
            return RouteDecision(
                route=RouteType.MISCONCEPTION_SKILL,
                confidence=0.88,
                reasons=self._get_misconception_reasons(context),
                skill_name="misconception-handling",
                retrieval_policy="required",
                fallback_route=RouteType.GROUNDED_RAG,
            )

        # 5.3 个性化解释 skill
        if self._should_use_explanation_skill(context):
            return RouteDecision(
                route=RouteType.PERSONALIZED_EXPLANATION_SKILL,
                confidence=0.85,
                reasons=self._get_explanation_reasons(context),
                skill_name="personalized-explanation",
                retrieval_policy="required",
                fallback_route=RouteType.GROUNDED_RAG,
            )

        # 6. Query rewrite 指向明确课程追问时，优先进入 grounded RAG。
        rewrite_decision = self._route_rewritten_followup(context)
        if rewrite_decision is not None:
            return rewrite_decision

        # 7. 课程知识问答类 - 明确概念/原理/定义类问题使用 grounded RAG
        if self._is_likely_course_question(context):
            return RouteDecision(
                route=RouteType.GROUNDED_RAG,
                confidence=0.80,
                reasons=["课程相关知识问答"],
                retrieval_policy="required",
                fallback_route=RouteType.GENERIC_AGENT,
            )

        # 8. 通用 agent fallback
        return RouteDecision(
            route=RouteType.GENERIC_AGENT,
            confidence=0.60,
            reasons=["未匹配到特定路由，使用通用 agent"],
            retrieval_policy="optional",
        )

    def _route_autonomous_tool_choice(self, context: QueryContext) -> Optional[RouteDecision]:
        """Return generic-agent routing for ambiguous code/example requests.

        The goal is not to enumerate every possible query by rules.  Instead we
        carve out broad ambiguity classes where deterministic RAG is harmful:
        code payloads, code generation, and Python demonstrations often require
        the agent to decide among direct explanation, code review, Python
        execution, and optional course retrieval.
        """

        intents = set(context.detected_intents or [])
        query = self._normalize(context.normalized_query)

        if "code_request" not in intents and not self._contains_code_payload(query):
            return None

        return RouteDecision(
            route=RouteType.GENERIC_AGENT,
            confidence=0.78,
            reasons=["代码/示例/实现类请求，交给 agent 自主选择工具"],
            retrieval_policy="optional",
            metadata={
                "autonomous_tool_choice": True,
                "allowed_tool_hints": [
                    "course_rag_tool",
                    "python_exec_tool",
                    "course_schedule_tool",
                    "current_datetime_tool",
                ],
            },
        )

    def _contains_code_payload(self, query: str) -> bool:
        """Best-effort broad code-payload detector used only to avoid forced RAG."""

        compact = "".join(query.split())
        return bool(
            _has_strong_python_signal(query)
            or _assignment_counts_as_code(query, compact)
        )

    def _route_rewritten_followup(self, context: QueryContext) -> Optional[RouteDecision]:
        rewrite = context.metadata.get("rewrite") if context.metadata else None
        if not isinstance(rewrite, dict):
            return None
        if not rewrite.get("changed"):
            return None

        confidence = float(rewrite.get("confidence") or 0.0)
        strategy = rewrite.get("strategy") or "unknown"
        rewritten_query = rewrite.get("rewritten_query") or context.enriched_query or context.normalized_query

        # 只提升高置信、实体级补全；普通 contextual_followup 仍交给原路由。
        if confidence < 0.75 or strategy not in {"entity_followup", "svm_kernel_followup"}:
            return None

        return RouteDecision(
            route=RouteType.GROUNDED_RAG,
            confidence=max(0.82, min(0.90, confidence)),
            reasons=["query rewrite 指向课程追问", f"rewrite_strategy={strategy}"],
            retrieval_policy="required",
            fallback_route=RouteType.GENERIC_AGENT,
            metadata={
                "rewrite_strategy": strategy,
                "rewrite_confidence": confidence,
                "rewritten_query": rewritten_query,
            },
        )

    # ========== 系统工具判断 ==========

    def is_datetime_request(self, query: str) -> bool:
        """Public datetime-query predicate shared with rewriter/agent."""
        return is_datetime_request(query)

    def is_schedule_request(self, query: str) -> bool:
        """Public schedule-query predicate shared with rewriter/agent."""
        return is_schedule_request(query)

    def _is_datetime_request(self, query: str) -> bool:
        """Compatibility wrapper for existing tests/callers."""
        return self.is_datetime_request(query)

    def _is_schedule_request(self, query: str) -> bool:
        """Compatibility wrapper for existing tests/callers."""
        return self.is_schedule_request(query)

    # ========== 教学策略判断 ==========

    def _should_use_learning_path_skill(self, context: QueryContext) -> bool:
        """判断是否使用学习路径 skill。

        关键词列表对齐旧的 AgentService._is_learning_path_request，
        同时继续要求现有 SkillLoader 选中 learning-path，降低行为变化风险。
        """
        if "learning-path" not in context.skill_candidate_keys:
            return False

        query = self._normalize(context.normalized_query)
        direct_cues = [
            "学习路线",
            "学习路径",
            "学习计划",
            "复习路线",
            "复习计划",
            "学习顺序",
            "复习顺序",
            "路线图",
        ]
        if any(cue in query for cue in direct_cues):
            return True

        soft_cues = [
            "怎么学",
            "如何学",
            "先学什么",
            "后学什么",
            "先看什么",
            "怎么复习",
            "如何复习",
            "怎么安排",
            "如何安排",
            "怎么入门",
        ]
        return any(cue in query for cue in soft_cues)

    def _get_learning_path_reasons(self, context: QueryContext) -> list:
        """获取学习路径路由的原因"""
        reasons = []
        query = self._normalize(context.normalized_query)

        if any(kw in query for kw in ["学习路线", "怎么学", "学习计划", "复习计划", "路线图"]):
            reasons.append("检测到学习路径关键词")

        if context.detected_concepts:
            concepts = [c.concept_id for c in context.detected_concepts[:2]]
            reasons.append(f"识别到概念: {', '.join(concepts)}")

        if context.profile_snapshot and context.profile_snapshot.get("weak_spots", 0) > 0:
            reasons.append("学生画像存在薄弱点")

        return reasons

    def _should_use_misconception_skill(self, context: QueryContext) -> bool:
        """判断是否使用错误理解处理 skill"""
        query = self._normalize(context.normalized_query)

        # 反复不懂信号
        clarification_keywords = [
            "不太懂", "不理解", "不明白", "没懂",
            "还是不懂", "还是不理解", "为什么不是",
        ]

        has_clarification = any(kw in query for kw in clarification_keywords)

        # 判断题型（容易出现错误理解）
        judgment_patterns = [
            r"(对|错|正确|不正确|是否|是不是|能否|可以|可不可以)",
        ]
        has_judgment = any(re.search(p, query) for p in judgment_patterns)

        # skill 候选中有 misconception
        in_candidates = "misconception-handling" in context.skill_candidate_keys

        # 保持与旧逻辑一致：只要 SkillLoader 选中了 misconception-handling，
        # 就允许进入该技能。
        return in_candidates

    def _get_misconception_reasons(self, context: QueryContext) -> list:
        """获取错误理解路由的原因"""
        reasons = []
        query = self._normalize(context.normalized_query)

        if any(kw in query for kw in ["不太懂", "不理解", "还是不懂"]):
            reasons.append("检测到反复澄清信号")

        if re.search(r"(对|错|正确|是否)", query):
            reasons.append("判断题型，易出现理解偏差")

        if context.is_clarification_signal:
            reasons.append("澄清请求信号")

        return reasons

    def _has_explicit_misconception_signal(self, context: QueryContext) -> bool:
        """Whether the question contains a strong wrong-premise signal.

        This intentionally stays narrower than generic clarification signals
        like “不懂/为什么”.  It only lets misconception skill preempt autonomous
        tool choice when the student appears to assert or test a possibly wrong
        belief.
        """

        query = self._normalize(context.normalized_query)
        cues = [
            "我以为",
            "一直以为",
            "难道不是",
            "我觉得是",
            "我认为",
            "不该是",
            "应该算",
            "应该不是",
            "应该是",
            "本质上",
            "就是无监督",
            "就是监督",
            "属于无监督",
            "属于监督",
            "等于降维",
            "就是算法",
            "就是模型",
            "是无监督算法",
            "是监督学习",
        ]
        return any(cue in query for cue in cues)

    def _should_use_explanation_skill(self, context: QueryContext) -> bool:
        """判断是否使用个性化解释 skill。

        语义对齐旧的 AgentService._should_use_explanation_skill：
        - 必须被现有 SkillLoader 选中；
        - 无概念时，仅个性化请求 + 有画像上下文才触发；
        - 有概念时，根据匹配分数、个性化请求、判断题和画像上下文触发。
        """
        if "personalized-explanation" not in context.skill_candidate_keys:
            return False

        if not context.detected_concepts:
            return (
                self._is_personalization_request(context.normalized_query)
                and self._has_personalization_context(context)
            )

        primary_score = context.detected_concepts[0].confidence
        if primary_score < 0.45:
            return False

        if self._is_personalization_request(context.normalized_query):
            return True

        if self._is_judgement_question(context.normalized_query) and primary_score >= 0.7:
            return True

        return self._has_personalization_context(context) and primary_score >= 0.6

    def _get_explanation_reasons(self, context: QueryContext) -> list:
        """获取个性化解释路由的原因"""
        reasons = []
        query = self._normalize(context.normalized_query)

        if self._is_personalization_request(query):
            reasons.append("检测到个性化解释请求")

        if self._is_judgement_question(query):
            reasons.append("判断题型，适合个性化澄清")

        if context.detected_concepts:
            concepts = [c.concept_id for c in context.detected_concepts[:2]]
            reasons.append(f"识别到概念: {', '.join(concepts)}")

        if self._has_personalization_context(context):
            reasons.append("存在可用学生画像上下文")

        return reasons

    def _is_personalization_request(self, query: str) -> bool:
        """判断是否是个性化解释请求。"""
        normalized = self._normalize(query)
        cues = [
            "结合我现在的进度",
            "按我现在的进度",
            "我现在的进度",
            "我已经学过",
            "结合我已经学过",
            "我之前",
            "老是学不会",
            "容易混淆",
            "更直观",
            "怎么学习比较合适",
            "怎么给我梳理",
        ]
        return any(cue in normalized for cue in cues)

    def _has_personalization_context(self, context: QueryContext) -> bool:
        """判断是否存在可用于个性化的画像上下文。"""
        snapshot = context.profile_snapshot or {}
        return bool(
            snapshot.get("current_chapter")
            or snapshot.get("recent_concepts")
            or snapshot.get("weak_spots", 0)
            or snapshot.get("pending_weak_spots", 0)
        )

    def _is_judgement_question(self, query: str) -> bool:
        """判断是否是判断型问题。"""
        return is_judgement_question(query)

    # ========== 课程知识判断 ==========

    def _is_likely_course_question(self, context: QueryContext) -> bool:
        """判断是否可能是课程相关问题。

        不能恒返回 True，否则 GENERIC_AGENT 永远不可达。这里采用保守判断：
        有课程概念、课程相关意图，或命中数据科学/机器学习常见词汇时才走 RAG。
        """
        if context.detected_concepts:
            return True

        course_related_intents = [
            "concept_explanation",
            "comparison",
            "application",
        ]
        if any(intent in context.detected_intents for intent in course_related_intents):
            return True

        query = self._normalize(context.normalized_query)
        if self._is_hyperparameter_concept_question(query):
            return True

        course_keywords = [
            "数据科学", "数据分析", "机器学习", "深度学习",
            "统计", "概率", "模型", "算法", "特征", "训练",
            "测试集", "验证集", "回归", "分类", "聚类",
            "决策树", "随机森林", "svm", "支持向量机",
            "梯度下降", "过拟合", "欠拟合", "正则化",
            "交叉验证", "贝叶斯", "神经网络",
        ]
        return any(keyword in query for keyword in course_keywords)

    def _is_hyperparameter_concept_question(self, query: str) -> bool:
        """Detect natural-language ML hyperparameter questions with ``name=value``.

        These look syntactically like assignments but semantically ask about a
        course concept, e.g. ``alpha=0.01 为什么更好`` or ``C=1 和 C=10 的区别``.
        """

        if not _has_concept_question_cue(query):
            return False

        hyperparameter_pattern = (
            r"(?<![A-Za-z0-9_])"
            r"(?:"
            r"alpha|learning_rate|lr|gamma|lambda|lambda_|c|k|"
            r"max_depth|min_samples_split|min_samples_leaf|n_estimators|"
            r"n_neighbors|degree|coef0|batch_size|epoch|epochs"
            r")\s*="
        )
        return bool(
            "超参数" in query
            or "正则化系数" in query
            or "惩罚系数" in query
            or re.search(hyperparameter_pattern, query, flags=re.IGNORECASE)
        )


_router: Optional[QueryRouter] = None


def get_router() -> QueryRouter:
    """获取路由器单例"""
    global _router
    if _router is None:
        _router = QueryRouter()
    return _router
