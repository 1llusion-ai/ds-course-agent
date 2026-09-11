"""Explicit course evidence requests must not depend on the semantic router."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ds_course_agent.agent.routing.models import ExecutionMode, RetrievalPolicy
from ds_course_agent.agent.routing.preprocessor import QueryPreprocessor
from ds_course_agent.agent.routing.router import QueryRouter


@pytest.mark.parametrize(
    "query",
    [
        "根据教材，参加 Kaggle 数据竞赛的一般流程是什么？",
        "请依据课程资料介绍竞赛流程",
        "基于课件解释数据分组后的聚合过程",
        "dmki是什么？",
        "dikw是什么？",
        "DIKW是什么？",
    ],
)
def test_explicit_evidence_requests_bypass_an_unavailable_semantic_router(query):
    context = QueryPreprocessor(enable_concept_detection=False).process(query, "session", "student", [])
    semantic_router = MagicMock()
    semantic_router.route.side_effect = AssertionError("explicit evidence requests must not need a model")

    decision = QueryRouter(semantic_router=semantic_router).route(context)

    assert decision.execution_mode is ExecutionMode.GROUNDED_GENERATION
    assert decision.retrieval_policy is RetrievalPolicy.REQUIRED
    assert decision.allowed_tools == ()
    semantic_router.route.assert_not_called()


@pytest.mark.parametrize("query", ["不用根据教材回答", "我不是让你根据教材介绍", "如何参加 Kaggle 竞赛？"])
def test_course_evidence_signal_requires_an_explicit_positive_request(query):
    context = QueryPreprocessor(enable_concept_detection=False).process(query, "session", "student", [])
    assert context.course_evidence_requested is False


def test_web_search_keeps_precedence_over_the_requested_course_source():
    context = QueryPreprocessor(enable_concept_detection=False).process(
        "根据教材介绍竞赛流程", "session", "student", []
    )
    context.web_search_requested = True

    assert QueryRouter().route(context).execution_mode is ExecutionMode.WEB_PIPELINE
