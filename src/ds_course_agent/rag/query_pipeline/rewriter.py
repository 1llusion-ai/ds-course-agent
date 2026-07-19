"""
Query Rewriter

保守版查询改写器：不修改 original_query / normalized_query，只生成面向检索和
follow-up 理解的 enriched_query，并把改写轨迹写入类型化 QueryContext。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import QueryContext, QueryRewriteTrace
from .utils import (
    build_grounded_context_query,
    collect_recent_context,
    is_contextual_followup,
    is_datetime_request,
    is_schedule_request,
    normalize_query_text,
)

COURSE_ENTITY_ALIASES = [
    ("SVM 的核函数", ["svm的核函数", "支持向量机的核函数", "核函数", "线性核", "kernel"]),
    ("支持向量机", ["svm", "支持向量机"]),
    ("决策树", ["决策树", "decisiontree", "decision tree"]),
    ("随机森林", ["随机森林", "randomforest", "random forest"]),
    ("PCA", ["pca", "主成分分析", "主成分"]),
    ("梯度下降", ["梯度下降", "gradientdescent", "gradient descent"]),
    ("逻辑回归", ["逻辑回归", "logisticregression", "logistic regression"]),
    ("线性回归", ["线性回归", "linearregression", "linear regression"]),
    ("朴素贝叶斯", ["朴素贝叶斯", "naivebayes", "naive bayes", "贝叶斯"]),
    ("KNN", ["knn", "k近邻", "k近邻算法"]),
]

PRONOUN_PREFIXES = ["它", "这个", "那个", "上述", "刚才那个", "前面那个", "前面说的"]


@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str
    enriched_query: str
    changed: bool
    strategy: str = "none"
    reason: str = ""
    confidence: float = 0.0


class QueryRewriter:
    """规则优先、零外部调用的保守 Query Rewriter。"""

    def rewrite(self, context: QueryContext) -> RewriteResult:
        original_query = context.original_query
        normalized_query = context.normalized_query or original_query

        if self._should_skip(normalized_query):
            result = RewriteResult(
                original_query=original_query,
                rewritten_query=normalized_query,
                enriched_query=normalized_query,
                changed=False,
                strategy="skip_system_query",
                reason="系统工具类查询不改写",
                confidence=1.0,
            )
            self._apply(context, result)
            return result

        recent_context = self._collect_recent_context(context.chat_history)
        specific_rewrite = self._rewrite_specific_followup(normalized_query, recent_context)
        if specific_rewrite and specific_rewrite != normalized_query:
            enriched_query = self._build_grounded_query(specific_rewrite, recent_context)
            result = RewriteResult(
                original_query=original_query,
                rewritten_query=specific_rewrite,
                enriched_query=enriched_query,
                changed=True,
                strategy="svm_kernel_followup",
                reason="根据最近 SVM/核函数上下文消解指代",
                confidence=0.90,
            )
            self._apply(context, result)
            return result

        entity_rewrite = self._rewrite_entity_followup(normalized_query, recent_context)
        if entity_rewrite and entity_rewrite != normalized_query:
            enriched_query = self._build_grounded_query(entity_rewrite, recent_context)
            result = RewriteResult(
                original_query=original_query,
                rewritten_query=entity_rewrite,
                enriched_query=enriched_query,
                changed=True,
                strategy="entity_followup",
                reason="根据最近课程实体补全追问",
                confidence=0.78,
            )
            self._apply(context, result)
            return result

        if self._looks_contextual_followup(normalized_query) and recent_context.strip():
            enriched_query = self._build_grounded_query(normalized_query, recent_context)
            result = RewriteResult(
                original_query=original_query,
                rewritten_query=normalized_query,
                enriched_query=enriched_query,
                changed=True,
                strategy="contextual_followup",
                reason="检测到追问/指代，补充最近对话上下文用于检索",
                confidence=0.70,
            )
            self._apply(context, result)
            return result

        result = RewriteResult(
            original_query=original_query,
            rewritten_query=normalized_query,
            enriched_query=normalized_query,
            changed=False,
            strategy="none",
            reason="未检测到需要改写的上下文追问",
            confidence=0.0,
        )
        self._apply(context, result)
        return result

    def _apply(self, context: QueryContext, result: RewriteResult) -> None:
        context.enriched_query = result.enriched_query
        context.rewrite_trace = QueryRewriteTrace(
            original_query=result.original_query,
            rewritten_query=result.rewritten_query,
            enriched_query=result.enriched_query,
            changed=result.changed,
            strategy=result.strategy,
            reason=result.reason,
            confidence=result.confidence,
        )

    def _should_skip(self, query: str) -> bool:
        normalized = normalize_query_text(query)
        return is_datetime_request(normalized) or is_schedule_request(normalized)

    def _rewrite_specific_followup(self, query: str, recent_context: str) -> str | None:
        normalized_query = normalize_query_text(query)
        normalized_context = normalize_query_text(recent_context)
        if not recent_context.strip():
            return None

        has_svm_kernel_context = any(
            token in normalized_context for token in ["svm", "支持向量机", "核函数", "线性核", "kernel"]
        )
        asks_linear_separable_kernel = (
            "线性可分" in normalized_query
            and any(token in normalized_query for token in ["它", "还需要", "需要吗", "用吗"])
            and has_svm_kernel_context
        )
        if asks_linear_separable_kernel:
            return "SVM 的核函数在线性可分时还需要吗？"

        return None

    def _rewrite_entity_followup(self, query: str, recent_context: str) -> str | None:
        if not recent_context.strip():
            return None

        entity = self._latest_context_entity(recent_context)
        if not entity:
            return None

        normalized_query = normalize_query_text(query)
        normalized_entity = normalize_query_text(entity)
        if normalized_entity in normalized_query:
            return None

        # 指代型短追问：它效果怎么样？ -> SVM 的核函数效果怎么样？
        pronoun_rewrite = self._replace_pronoun_prefix(query, entity)
        if pronoun_rewrite:
            return pronoun_rewrite

        # 保守主题补全：仅在问题包含跨实体常见属性时补全最近实体。
        if self._should_prefix_recent_entity(normalized_query, normalized_entity):
            return f"{entity}{query}"

        return None

    def _latest_context_entity(self, recent_context: str) -> str | None:
        normalized_context = normalize_query_text(recent_context)
        latest: tuple[int, str] | None = None
        for canonical, aliases in COURSE_ENTITY_ALIASES:
            positions = [normalized_context.rfind(normalize_query_text(alias)) for alias in aliases]
            position = max(positions) if positions else -1
            if position < 0:
                continue
            if latest is None or position > latest[0]:
                latest = (position, canonical)
        return latest[1] if latest else None

    def _replace_pronoun_prefix(self, query: str, entity: str) -> str | None:
        stripped = query.strip()
        for pronoun in PRONOUN_PREFIXES:
            if stripped.startswith(pronoun):
                suffix = stripped[len(pronoun) :].lstrip("的")
                return f"{entity}{suffix}" if suffix else entity
        return None

    def _should_prefix_recent_entity(self, normalized_query: str, normalized_entity: str) -> bool:
        if len(normalized_query) > 24:
            return False
        if normalized_entity in normalized_query:
            return False

        topic_cues = [
            "过拟合",
            "欠拟合",
            "正则化",
            "剪枝",
            "泛化",
            "效果",
            "优缺点",
            "优点",
            "缺点",
            "怎么解决",
            "如何解决",
            "怎么办",
            "怎么处理",
            "为什么",
            "适用场景",
            "应用场景",
            "参数",
            "复杂度",
        ]
        return any(cue in normalized_query for cue in topic_cues)

    def _looks_contextual_followup(self, query: str) -> bool:
        return is_contextual_followup(query, allow_short_question=True)

    def _collect_recent_context(self, chat_history, limit: int = 4) -> str:
        return collect_recent_context(
            chat_history,
            limit=limit,
            include_roles=True,
            ai_truncate_chars=240,
        )

    def _build_grounded_query(self, rewritten_query: str, recent_context: str) -> str:
        return build_grounded_context_query(rewritten_query, recent_context)


_rewriter: QueryRewriter | None = None


def get_rewriter() -> QueryRewriter:
    """获取查询改写器单例。"""
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
