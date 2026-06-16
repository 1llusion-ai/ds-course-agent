"""
Query Rewriter

保守版查询改写器：不修改 original_query / normalized_query，只生成面向检索和
follow-up 理解的 enriched_query，并把改写轨迹写入 context.metadata["rewrite"]。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.messages import BaseMessage

from .models import QueryContext
from .router import QueryRouter
from .utils import normalize_query_text


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

    def __init__(self, router: Optional[QueryRouter] = None):
        self._router = router or QueryRouter()

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
        return (
            self._router._is_datetime_request(normalized)
            or self._router._is_schedule_request(normalized)
        )

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
        normalized = normalize_query_text(query)
        cues = [
            "它", "这个", "那个", "上述", "刚才", "前面", "继续", "再解释",
            "再讲", "展开", "详细说", "为什么", "还需要吗", "需要吗",
            "能再解释一下吗", "再解释一下", "什么意思", "怎么理解",
        ]
        if any(cue in normalized for cue in cues):
            return True
        return len(normalized) <= 12 and normalized.endswith(("吗", "呢", "？", "?"))

    def _collect_recent_context(self, chat_history: Optional[list[Any]], limit: int = 4) -> str:
        if not chat_history:
            return ""

        summary_messages = [msg for msg in chat_history if self._is_summary_message(msg)]
        regular_messages = [msg for msg in chat_history if not self._is_summary_message(msg)]
        parts = []

        if summary_messages:
            summary_content = self._message_content(summary_messages[-1])
            if summary_content:
                parts.append(summary_content)

        for msg in regular_messages[-limit:]:
            content = self._message_content(msg)
            if not content:
                continue
            role = self._message_role(msg)
            if role == "human":
                parts.append(f"用户: {content}")
            elif role == "ai":
                parts.append(f"助手: {content[:240]}")
            else:
                parts.append(content[:240])

        return "\n".join(parts)

    def _is_summary_message(self, msg: Any) -> bool:
        if isinstance(msg, BaseMessage):
            return getattr(msg, "type", "") == "system" and bool(
                getattr(msg, "additional_kwargs", {}).get("short_memory_summary")
            )
        if isinstance(msg, dict):
            return msg.get("role") == "system" and bool(
                msg.get("additional_kwargs", {}).get("short_memory_summary")
            )
        return False

    def _message_role(self, msg: Any) -> str:
        if isinstance(msg, BaseMessage):
            return getattr(msg, "type", "")
        if isinstance(msg, dict):
            role = msg.get("role", "")
            return {"user": "human", "assistant": "ai", "system": "system"}.get(role, role)
        return ""

    def _message_content(self, msg: Any) -> str:
        content = getattr(msg, "content", None) if isinstance(msg, BaseMessage) else None
        if isinstance(msg, dict):
            content = msg.get("content", "")
        if isinstance(content, str):
            return re.sub(r"\s+", " ", content).strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return re.sub(r"\s+", " ", " ".join(parts)).strip()
        return re.sub(r"\s+", " ", str(content or "")).strip()

    def _build_grounded_query(self, rewritten_query: str, recent_context: str) -> str:
        if not recent_context.strip():
            return rewritten_query
        return (
            "最近对话上下文：\n"
            f"{recent_context}\n\n"
            "请结合上下文理解学生当前追问，再检索课程资料回答。\n"
            f"当前问题：{rewritten_query}"
        )


_rewriter: Optional[QueryRewriter] = None


def get_rewriter() -> QueryRewriter:
    """获取查询改写器单例。"""
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
