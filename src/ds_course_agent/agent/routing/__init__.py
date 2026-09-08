"""
Query Pipeline 模块

提供统一的查询处理流程：
  Query → Preprocessor → Router → Inline Execution → Postprocessor → Response
"""

from .models import (
    DetectedConcept,
    EnrichmentPlan,
    ExecutionMode,
    FinalResponse,
    QueryContext,
    QueryRewriteTrace,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from .pipeline import QueryPipeline
from .postprocessor import QueryPostprocessor, get_postprocessor
from .preprocessor import QueryPreprocessor, get_preprocessor
from .rewriter import QueryRewriter, RewriteResult, get_rewriter
from .router import QueryRouter, get_router

__all__ = [
    "QueryContext",
    "RouteDecision",
    "RouteState",
    "RouteExecutionResult",
    "FinalResponse",
    "QueryRewriteTrace",
    "RouteFamily",
    "RouteIntent",
    "ExecutionMode",
    "EnrichmentPlan",
    "RetrievalPolicy",
    "DetectedConcept",
    "QueryPipeline",
    "QueryPreprocessor",
    "get_preprocessor",
    "QueryRouter",
    "get_router",
    "QueryPostprocessor",
    "get_postprocessor",
    "QueryRewriter",
    "RewriteResult",
    "get_rewriter",
]
