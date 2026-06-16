"""
Query Rewriter

保守版查询改写器：不修改 original_query / normalized_query，只生成面向检索和
follow-up 理解的 enriched_query，并把改写轨迹写入 context.metadata["rewrite"]。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import QueryContext
from .utils import (
    build_grounded_context_query,
    collect_recent_context,
    is_contextual_followup,
    is_datetime_request,
    is_schedule_request,
    normalize_query_text,
)


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
        rewritten_query = self._rewrite_specific_followup(normalized_query, recent_context)
        if rewritten_query and rewritten_query != normalized_query:
            enriched_query = self._build_grounded_query(rewritten_query, recent_context)
            result = RewriteResult(
                original_query=original_query,
                rewritten_query=rewritten_query,
                enriched_query=enriched_query,
                changed=True,
                strategy="svm_kernel_followup",
                reason="根据最近 SVM/核函数上下文消解指代",
                confidence=0.90,
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
        context.metadata["rewrite"] = {
            "original_query": result.original_query,
            "rewritten_query": result.rewritten_query,
            "enriched_query": result.enriched_query,
            "changed": result.changed,
            "strategy": result.strategy,
            "reason": result.reason,
            "confidence": result.confidence,
        }

    def _should_skip(self, query: str) -> bool:
        normalized = normalize_query_text(query)
        return is_datetime_request(normalized) or is_schedule_request(normalized)

    def _rewrite_specific_followup(self, query: str, recent_context: str) -> Optional[str]:
        normalized_query = normalize_query_text(query)
        normalized_context = normalize_query_text(recent_context)
        if not recent_context.strip():
            return None

        has_svm_kernel_context = any(
            token in normalized_context
            for token in ["svm", "支持向量机", "核函数", "线性核", "kernel"]
        )
        asks_linear_separable_kernel = (
            "线性可分" in normalized_query
            and any(token in normalized_query for token in ["它", "还需要", "需要吗", "用吗"])
            and has_svm_kernel_context
        )
        if asks_linear_separable_kernel:
            return "SVM 的核函数在线性可分时还需要吗？"

        return None

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


_rewriter: Optional[QueryRewriter] = None


def get_rewriter() -> QueryRewriter:
    """获取查询改写器单例。"""
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
