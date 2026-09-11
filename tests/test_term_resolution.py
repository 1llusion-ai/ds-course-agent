"""Tests for conservative course-term lookup and correction."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from ds_course_agent.retrieval.term_resolution import (
    CourseTermIndex,
    CourseTermMatchKind,
)
from ds_course_agent.shared.term_queries import parse_short_term_query


def _term_index() -> CourseTermIndex:
    return CourseTermIndex(
        [
            Document(page_content="DIKW 金字塔表示从数据到智慧的转化。", metadata={"book_page": 16}),
            Document(page_content="数据科学研究包含从 DIKW 模型的数据到智慧。", metadata={"book_page": 23}),
            Document(page_content="BM25 是一种词项匹配方法。", metadata={"book_page": 200}),
            Document(page_content="BM25 也可用于检索。", metadata={"book_page": 201}),
        ]
    )


def test_exact_course_term_returns_only_direct_documents() -> None:
    lookup = _term_index().lookup("DIKW是什么？")

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.EXACT
    assert lookup.resolution.resolved_term == "DIKW"
    assert [document.metadata["book_page"] for document in lookup.documents] == [16, 23]
    assert all("DIKW" in document.page_content for document in lookup.documents)


def test_unique_nearby_course_term_corrects_typo() -> None:
    lookup = _term_index().lookup("DMKI是什么？")

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.CORRECTED
    assert lookup.resolution.requested_term == "DMKI"
    assert lookup.resolution.resolved_term == "DIKW"
    assert lookup.resolution.resolved_query == "DIKW是什么？"
    assert len(lookup.documents) == 2


def test_transposed_course_term_corrects_to_dikw() -> None:
    lookup = _term_index().lookup("KIDW是什么？")

    assert lookup is not None
    assert lookup.resolution.resolved_term == "DIKW"


def test_unknown_term_returns_no_documents_instead_of_semantic_neighbors() -> None:
    lookup = _term_index().lookup("ZZZZ是什么？")

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.UNRESOLVED
    assert lookup.resolution.resolved_term is None
    assert lookup.documents == ()


def test_multi_term_or_normal_question_stays_on_vector_retrieval() -> None:
    index = _term_index()

    assert index.lookup("DIKW 和 PCA 有什么区别？") is None
    assert index.lookup("为什么数据清洗很重要？") is None


@pytest.mark.parametrize(
    "question",
    [
        "如何用 Pandas 对数据分组后做聚合统计？",
        "参加 Kaggle 数据竞赛的一般流程是什么？",
        "PCA和线性回归有什么区别？",
        "用Pandas如何处理缺失值？",
        "请解释Python中的循环",
        "K-means是什么？",
        "k-means的原理是什么？",
        "TF-IDF的含义是什么？",
        "PCA怎么学比较好？",
        "请解释一下 PCA 对这个例子的作用",
    ],
)
def test_lookup_preserves_procedures_comparisons_and_compound_terms(question: str) -> None:
    assert parse_short_term_query(question) is None
    assert _term_index().lookup(question) is None


@pytest.mark.parametrize("question", ["DIKW", "DIKW 是什么？", "请解释 DIKW", "请问 DIKW 的定义？"])
def test_whole_definition_frames_retain_exact_lookup(question: str) -> None:
    lookup = _term_index().lookup(question)

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.EXACT
    assert lookup.resolution.resolved_query == question


def test_lowercase_unknown_term_is_not_auto_corrected() -> None:
    lookup = _term_index().lookup("dmki是什么？")

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.UNRESOLVED


def test_bca_corrects_to_unique_pca_course_term() -> None:
    index = CourseTermIndex(
        [
            Document(page_content="PCA 是主成分分析。", metadata={"book_page": 150}),
            Document(page_content="PCA 属于线性降维方法。", metadata={"book_page": 153}),
        ]
    )

    lookup = index.lookup("BCA是什么？")

    assert lookup is not None
    assert lookup.resolution.match_kind is CourseTermMatchKind.CORRECTED
    assert lookup.resolution.resolved_term == "PCA"
    assert lookup.resolution.resolved_query == "PCA是什么？"
