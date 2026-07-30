"""
Query Router

负责根据 QueryContext 决定路由策略
"""

import logging
import re
from typing import Any

import ds_course_agent.shared.config as config

from .models import ExecutionMode, QueryContext, RouteDecision, RouteFamily, RouteIntent
from .policy import build_learning_decision
from .preprocessor import (
    _assignment_counts_as_code,
    _has_assignment_signal,
    _has_concept_question_cue,
    _has_strong_python_signal,
)
from .route_rules import RouteRule, build_route_rules
from .utils import is_judgement_question, normalize_query_text

logger = logging.getLogger(__name__)


_UNAMBIGUOUS_HYPERPARAMETER_NAMES = [
    "alpha",
    "learning_rate",
    "lr",
    "eta",
    "gamma",
    "lambda",
    "lambda_",
    "max_depth",
    "min_samples_split",
    "min_samples_leaf",
    "n_estimators",
    "n_neighbors",
    "degree",
    "coef0",
    "batch_size",
    "epoch",
    "epochs",
    "epsilon",
    "eps",
    "momentum",
    "dropout",
    "dropout_rate",
    "beta",
    "beta1",
    "beta2",
    "weight_decay",
    "tol",
    "tolerance",
]

_AMBIGUOUS_HYPERPARAMETER_NAMES = [
    # Single-letter names are common ML hyperparameters, but too ambiguous to
    # route as course RAG without an ML/domain cue.
    "c",
    "k",
]

_UNAMBIGUOUS_HYPERPARAMETER_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(name) for name in _UNAMBIGUOUS_HYPERPARAMETER_NAMES) + r")\s*=",
    flags=re.IGNORECASE,
)

_AMBIGUOUS_HYPERPARAMETER_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(name) for name in _AMBIGUOUS_HYPERPARAMETER_NAMES) + r")\s*=",
    flags=re.IGNORECASE,
)

_HYPERPARAMETER_DOMAIN_CUES = [
    "超参数",
    "调参",
    "学习率",
    "正则化系数",
    "惩罚系数",
    "机器学习",
    "深度学习",
    "神经网络",
    "模型",
    "算法",
    "训练",
    "梯度下降",
    "正则化",
    "svm",
    "支持向量机",
    "kmeans",
    "k-means",
    "knn",
    "k近邻",
    "聚类",
    "分类",
    "回归",
    "决策树",
    "随机森林",
]

_DIRECT_CODE_EXAMPLE_CUES = [
    "演示",
    "示例",
    "样例",
    "例子",
    "代码",
    "实现",
    "怎么写",
    "写一段",
    "给我一段",
    "用python",
]


def _has_hyperparameter_domain_cue(query: str) -> bool:
    return any(cue in query for cue in _HYPERPARAMETER_DOMAIN_CUES)


def _has_hyperparameter_assignment(query: str) -> bool:
    if _UNAMBIGUOUS_HYPERPARAMETER_ASSIGNMENT_RE.search(query):
        return True
    return bool(_AMBIGUOUS_HYPERPARAMETER_ASSIGNMENT_RE.search(query) and _has_hyperparameter_domain_cue(query))


class QueryRouter:
    """查询路由器"""

    def __init__(self, semantic_router: Any | None = None):
        self._rules = build_route_rules(self)
        self._semantic_router = semantic_router

    def _normalize(self, query: str) -> str:
        """与 query_pipeline.utils.normalize_query_text 保持一致的路由归一化。

        中文用户输入中常见有被输入法插入的空格；旧逻辑会去除所有空白，
        Router 也必须保持一致，否则会出现静默路由漂移。
        """
        return normalize_query_text(query)

    def route(self, context: QueryContext, *, enricher: Any | None = None) -> RouteDecision:
        """
        根据 QueryContext 进行路由决策

        规则按 priority 升序求值，首个 match 生效。``enricher`` 是 QueryPipeline
        注入的惰性富化器，分两个 memoized 阶段：

        - 求值到 ``requires_skills`` 规则前调用 ``ensure_skills()``（廉价 skill_select）；
        - 求值到 ``requires_concepts`` 规则前调用 ``ensure_concepts()``（昂贵的
          concept_map + rewrite + profile）。

        高置信 fast-path 规则（二者皆 False）在富化前命中并短路——datetime/
        schedule/code/python 不触发任何富化；autonomous(p60) 与纯 skill 路由只触发
        廉价 skill_select，不跑 concept_map。无 ``enricher`` 时（契约测试/独立调用）
        规则在裸 context 上求值，保持向后兼容。

        Args:
            context: 查询上下文
            enricher: 可选惰性富化器，暴露 ``ensure_skills()``/``ensure_concepts()``
                与 ``concepts_ran``/``skills_ran``

        Returns:
            RouteDecision
        """
        for rule in self._rules:
            if enricher is not None:
                if rule.requires_skills:
                    enricher.ensure_skills()
                if rule.requires_concepts:
                    enricher.ensure_concepts()
            if rule.match_fn(context):
                return rule.build_decision(context)

        return self._route_semantic_fallback(context)

    @property
    def rules(self) -> tuple[RouteRule, ...]:
        """只读规则表，供契约测试确认优先级和覆盖面。"""
        return self._rules

    def _route_code_learning(self, context: QueryContext) -> RouteDecision | None:
        """Return a direct learning intent for explicit code/example requests."""

        intents = set(context.detected_intents or [])
        query = self._normalize(context.normalized_query)

        if "code_request" not in intents and not self._contains_code_payload(query):
            return None

        if self._is_direct_code_example_request(context, query):
            return build_learning_decision(
                RouteIntent.CODE_EXAMPLE,
                confidence=0.82,
                reasons=["代码/示例/演示请求，直接生成示例，不调用执行工具"],
            )

        return build_learning_decision(
            RouteIntent.CODE_EXPLANATION,
            confidence=0.78,
            reasons=["代码/示例/实现类请求，使用无工具代码讲解路径"],
        )

    def _is_direct_code_example_request(self, context: QueryContext, query: str) -> bool:
        """Return whether a code request should be answered directly.

        Requests like “请用 Python 演示一次交叉验证” ask for a code example, not
        for execution.  Letting the tool-capable agent handle those turns can
        make the model emit a hidden ``python_exec_tool`` call first, which
        buffers streaming and can produce a misleading “代码逻辑正确” answer.
        Explicit run/debug/review requests and pasted code remain outside this
        direct path.
        """

        intents = set(context.detected_intents or [])
        if "code_request" not in intents:
            return False
        if "python_execution" in intents or "code_review" in intents:
            return False
        if self._contains_code_payload(query):
            return False
        compact = "".join(query.split())
        return any(cue in compact for cue in _DIRECT_CODE_EXAMPLE_CUES)

    def _contains_code_payload(self, query: str) -> bool:
        """Best-effort broad code-payload detector used only to avoid forced RAG."""

        compact = "".join(query.split())
        return bool(_has_strong_python_signal(query) or _assignment_counts_as_code(query, compact))

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
            "不太懂",
            "不理解",
            "不明白",
            "没懂",
            "还是不懂",
            "还是不理解",
            "为什么不是",
        ]

        has_clarification = any(kw in query for kw in clarification_keywords)

        # 判断题型（容易出现错误理解）
        judgment_patterns = [
            r"(对|错|正确|不正确|是否|是不是|能否|可以|可不可以)",
        ]
        has_judgment = any(re.search(p, query) for p in judgment_patterns)

        # skill 候选中有 misconception
        in_candidates = "misconception-handling" in context.skill_candidate_keys

        # SkillLoader 的候选只表示“可能可用”，不能单独抢走事实/概念题。
        # 只有反复澄清、判断题或明确错误前提才进入 misconception skill；
        # 普通 “为什么/是什么/应该是什么值” 仍应走 grounded RAG。
        return bool(
            in_candidates and (has_clarification or has_judgment or self._has_explicit_misconception_signal(context))
        )

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
            "应该不是",
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

        if self._is_personalization_request(context.normalized_query):
            return True
        return False

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
            "结合我之前",
            "再解释一遍",
            "换一种方式讲",
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
        query = self._normalize(context.normalized_query)
        is_hyperparameter_concept = self._is_hyperparameter_concept_question(query)
        assignment_concept_without_course_signal = (
            _has_assignment_signal(query) and _has_concept_question_cue(query) and not is_hyperparameter_concept
        )

        if is_hyperparameter_concept:
            return True

        strong_course_keywords = [
            "数据科学",
            "数据分析",
            "机器学习",
            "深度学习",
            "测试集",
            "验证集",
            "逻辑回归",
            "线性回归",
            "回归模型",
            "聚类",
            "kmeans",
            "k-means",
            "knn",
            "k近邻",
            "pca",
            "主成分分析",
            "决策树",
            "随机森林",
            "svm",
            "支持向量机",
            "梯度下降",
            "过拟合",
            "欠拟合",
            "正则化",
            "交叉验证",
            "贝叶斯",
            "神经网络",
        ]
        if assignment_concept_without_course_signal:
            return False
        return any(keyword in query for keyword in strong_course_keywords)

    def _is_hyperparameter_concept_question(self, query: str) -> bool:
        """Detect natural-language ML hyperparameter questions with ``name=value``.

        These look syntactically like assignments but semantically ask about a
        course concept, e.g. ``alpha=0.01 为什么更好`` or ``C=1 和 C=10 的区别``.
        """

        if not _has_concept_question_cue(query):
            return False

        if any(cue in query for cue in ["超参数", "调参", "学习率", "正则化系数", "惩罚系数"]):
            return True

        return _has_hyperparameter_assignment(query)

    def _route_semantic_fallback(self, context: QueryContext) -> RouteDecision:
        """Classify ambiguous candidates without granting tool permissions."""

        semantic_router = self._semantic_router
        if semantic_router is None:
            try:
                from .semantic_router import get_learning_semantic_router

                semantic_router = get_learning_semantic_router()
            except Exception:
                semantic_router = None

        if semantic_router is None:
            return self._clarification_decision(context, "semantic_router_unavailable")

        output = semantic_router.route(context.original_query, context.recent_context)
        intent = output.intent
        if float(output.confidence) < float(config.ROUTER_MIN_CONFIDENCE):
            return self._clarification_decision(context, "semantic_router_low_confidence")
        if intent is RouteIntent.NOT_LEARNING:
            context.special_case_response = (
                "这个问题目前不属于《数据科学导论》课程学习范围。"
                "你可以换成课程概念、代码练习、学习规划或课程安排相关的问题。"
            )
            return RouteDecision(
                family=RouteFamily.BOUNDARY,
                intent=RouteIntent.REFUSAL,
                execution_mode=ExecutionMode.STATIC_RESPONSE,
                confidence=float(output.confidence),
                reasons=["semantic_router=not_learning"],
            )
        if intent is RouteIntent.NEEDS_CLARIFICATION or output.needs_clarification:
            return self._clarification_decision(context, "semantic_router_needs_clarification")
        if intent is RouteIntent.CODE_EXECUTION and "python_execution" not in set(context.detected_intents or []):
            return self._clarification_decision(context, "code_execution_requires_explicit_signal")

        return build_learning_decision(
            intent,
            confidence=float(output.confidence),
            reasons=["learning semantic router"],
            requires_course_grounding=self._explicit_course_grounding_requested(context.normalized_query),
        )

    def _clarification_decision(self, context: QueryContext, reason: str) -> RouteDecision:
        context.special_case_response = (
            "我还不确定你是想了解课程概念、检查代码、运行代码，还是规划学习。请补充一个具体知识点、代码片段或学习目标。"
        )
        return RouteDecision(
            family=RouteFamily.BOUNDARY,
            intent=RouteIntent.NEEDS_CLARIFICATION,
            execution_mode=ExecutionMode.STATIC_RESPONSE,
            confidence=0.0,
            reasons=[reason],
        )

    def _explicit_course_grounding_requested(self, query: str) -> bool:
        normalized = self._normalize(query)
        return any(
            cue in normalized
            for cue in (
                "根据教材",
                "依据教材",
                "按照教材",
                "根据课程资料",
                "依据课程资料",
                "课程材料里",
            )
        )


_router: QueryRouter | None = None


def get_router() -> QueryRouter:
    """获取路由器单例"""
    global _router
    if _router is None:
        _router = QueryRouter()
    return _router
