"""Regression contracts for concept-specific assessment evidence selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ds_course_agent.assessment.evidence import (
    AssessmentTarget,
    InvalidAssessmentTarget,
    resolve_target,
    select_evidence,
)
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.service import AssessmentService, NoAssessmentEvidence


def _doc(text: str, **metadata: object) -> SimpleNamespace:
    return SimpleNamespace(page_content=text, metadata=metadata)


def _select(
    documents: list,
    target: AssessmentTarget,
    count: int = 1,
    budget: int = 6000,
    evidence_window_reader=None,
) -> list:
    return select_evidence(
        documents,
        target,
        max_sources=3,
        max_chars=budget,
        question_count=count,
        evidence_window_reader=evidence_window_reader,
    )


def _production_metadata(page_text: str, page: int = 126) -> dict[str, object]:
    return {
        "metadata_schema_version": "retrieval-provenance/1.0",
        "source": "decision-tree.pdf",
        "source_id": "decision-tree",
        "source_page": page,
        "book_page": page,
        "source_char_start": 0,
        "source_char_end": len(page_text),
        "source_page_sha256": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
        "source_page_text": page_text,
        "chunk_id": f"decision-tree-{page}",
        "chunk_type": "semantic",
    }


class _WindowReader:
    def __init__(self, pages: list) -> None:
        self.pages = pages

    def read_evidence_window(self, _document):
        return self.pages


def _page(text: str, page: int = 126) -> SimpleNamespace:
    return _doc(text, source_id="decision-tree", source_page=page, book_page=page, source="decision-tree.pdf")


def test_resolve_identity_and_aliases_without_neighbor_expansion() -> None:
    target = resolve_target(GenerateQuestionsRequest(target_kc_id="groupby_aggregation"))
    assert target.name == "分组聚合"
    assert "groupby" in target.query
    assert "排序" not in target.query
    assert target.chapter == "第4章"


def test_unknown_identity_never_retrieves() -> None:
    retriever = Mock()
    with pytest.raises(InvalidAssessmentTarget):
        AssessmentService(retriever=retriever).generate(GenerateQuestionsRequest(target_kc_id="missing"))
    retriever.retrieve.assert_not_called()


def test_target_excerpts_exclude_adjacent_apply_and_deduplicate() -> None:
    target = resolve_target(GenerateQuestionsRequest(target_kc_id="groupby_aggregation"))
    related = "groupby 按照指定字段对数据分组，随后可以使用 count 方法统计各组的数量。"
    unrelated = "DataFrame 的 apply 方法设置 axis=1 时会按行执行给定函数。"
    sources = _select([_doc(unrelated + related), _doc(related)], target)
    assert len(sources) == 1
    assert sources[0].text == related
    assert not _select([_doc(related), _doc(related)], target, count=2)


def test_contents_does_not_count_as_evidence() -> None:
    target = resolve_target(GenerateQuestionsRequest(target_kc_id="large_language_model"))
    toc = "9.1 自然语言处理 199 9.2 大语言模型概念 202 9.3 大语言模型应用 206 9.4 提示工程 208"
    assert not _select([_doc(toc)], target)
    assert not _select(
        [_doc("大语言模型的概念及其应用在本章进行详细介绍，包含预训练与生成。", chunk_type="toc")], target
    )


def test_wrong_chapter_does_not_pass_without_target_and_right_chapter_is_soft_preference() -> None:
    target = resolve_target(GenerateQuestionsRequest(target_kc_id="cross_validation"))
    wrong = _doc("打印训练集和验证集上的损失，可以观察模型的训练收敛过程。", chapter_no="第6章")
    good = _doc("交叉验证通过轮换不同的数据划分来评估模型，从而降低单次划分造成的偶然影响。", chapter_no="第8章")
    preferred = _doc("交叉验证通常将各折的评估结果进行汇总，用于估计模型在未见数据上的性能。", chapter_no="第6章")
    sources = _select([wrong, good, preferred], target, count=2)
    assert len(sources) == 2
    assert sources[0].text == preferred.page_content


def test_insufficient_or_truncated_evidence_never_calls_generator() -> None:
    retriever = Mock()
    retriever.retrieve.return_value = SimpleNamespace(
        documents=[_doc("交叉验证技术是 sklearn 提供的评估工具之一，可用于评估模型性能。")]
    )
    generator = Mock()
    with pytest.raises(NoAssessmentEvidence):
        AssessmentService(retriever=retriever, generator=generator).generate(
            GenerateQuestionsRequest(target_kc_id="cross_validation", count=2)
        )
    generator.generate_candidates.assert_not_called()
    with pytest.raises(NoAssessmentEvidence):
        AssessmentService(retriever=retriever, generator=generator, context_max_chars=10).generate(
            GenerateQuestionsRequest(target_kc_id="cross_validation", count=1)
        )
    generator.generate_candidates.assert_not_called()


def test_old_v2_metadata_never_defaults_to_complete_evidence() -> None:
    target = AssessmentTarget(None, "信息增益", ("信息增益",))
    document = _doc(
        "决策树使用信息增益选择划分属性，这是一条长度足够但来自旧索引的教材说明。",
        parser_source="marker_v2",
        source="decision-tree.pdf",
        source_page=126,
        chunk_id="legacy",
    )

    assert not _select([document], target)


def test_production_page_discards_truncated_outer_sentences() -> None:
    target = AssessmentTarget(None, "信息增益", ("信息增益", "增益率"))
    page_text = (
        "上一页延续到这里才结束。"
        "决策树使用信息增益选择划分属性，该指标反映划分前后数据不确定性的变化。"
        "为此可以引入阈值，如果某节点处最优划分属性的信息增益（或"
    )
    document = _doc(page_text, **_production_metadata(page_text))
    sources = _select([document], target, evidence_window_reader=_WindowReader([_page(page_text)]))

    assert len(sources) == 1
    assert "反映划分前后数据不确定性的变化" in sources[0].text
    assert "信息增益（或" not in sources[0].text


def test_production_page_with_invalid_hash_is_not_publishable() -> None:
    target = AssessmentTarget(None, "信息增益", ("信息增益",))
    page_text = "开头说明。决策树使用信息增益选择划分属性，这是一条完整教材说明。结尾说明。"
    metadata = _production_metadata(page_text)
    metadata["source_page_sha256"] = "0" * 64

    assert not _select(
        [_doc(page_text, **metadata)],
        target,
        evidence_window_reader=_WindowReader([_page(page_text)]),
    )


def test_malformed_formula_evidence_is_not_publishable() -> None:
    target = AssessmentTarget(None, "增益率", ("增益率",))
    malformed = _doc(r"决策树的增益率定义为 $G_r(D,a)=\frac{G(D | a}{H_a(D)}$，该公式用于属性选择。")

    assert not _select([malformed], target)


def test_unmatched_closer_inside_ocr_sentence_is_not_publishable() -> None:
    target = AssessmentTarget(None, "增益率", ("增益率",))
    corrupted = _doc("常用评价指标增益率）小于该阈值，则停止划分并将当前节点作为叶节点。")

    assert not _select([corrupted], target)


def test_complete_internal_formula_survives_incomplete_chunk_edges() -> None:
    target = AssessmentTarget(None, "增益率", ("增益率",))
    page_text = (
        "上一栏残留内容结束。"
        r"增益率定义为 $G_r(D,a)=\frac{G(D | a)}{H_a(D)}$，用于抑制多取值属性偏好。"
        "下一栏内容被截断（或"
    )
    document = _doc(page_text, **_production_metadata(page_text))

    sources = _select([document], target, evidence_window_reader=_WindowReader([_page(page_text)]))

    assert len(sources) == 1
    assert r"G_r(D,a)=\frac{G(D | a)}{H_a(D)}" in sources[0].text
    assert "下一栏内容被截断" not in sources[0].text


def test_conflicting_formula_sources_are_not_publishable() -> None:
    target = AssessmentTarget(None, "增益率", ("增益率",))
    documents = [
        _doc(r"增益率定义为 $G_r(D,a)=\frac{G(D | a)}{H_a(D)}$，用于属性选择。"),
        _doc(r"增益率定义为 $G_r(D,a)=\frac{G(D,a)}{H_a(D)}$，用于属性选择。"),
    ]

    assert not _select(documents, target)


def test_legacy_frozen_candidates_fail_closed_under_production_provenance() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "data"
    fixture = json.loads((root / "assessment_evidence_regression.json").read_text(encoding="utf-8"))
    baseline = json.loads((root / "assessment_generation_baseline.json").read_text(encoding="utf-8"))
    assert fixture["seed"] == baseline["seed"] == 4027065355
    assert [c["concept_id"] for c in fixture["cases"]] == [b["id"] for b in baseline["batches"]]
    assert sum(len(b["quiz"]["questions"]) for b in baseline["batches"]) == 10
    for case in fixture["cases"]:
        target = resolve_target(GenerateQuestionsRequest(target_kc_id=case["concept_id"], count=2))
        sources = _select([_doc(d["text"], **d["metadata"]) for d in case["documents"]], target, count=2)
        assert not sources, case["concept_id"]
