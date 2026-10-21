"""Digital-literacy resource and teaching-boundary regressions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from graphlib import TopologicalSorter

import pytest

from ds_course_agent.agent.prompt import get_system_prompt
from ds_course_agent.api.routers.profile import get_concept_detail
from ds_course_agent.assessment.evidence import resolve_target
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.courses import CourseCatalog
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.knowledge_map import get_knowledge_map
from ds_course_agent.teaching.knowledge_mapper import get_knowledge_mapper, map_question_to_concepts


def _digital_literacy_course():
    return CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require("digital-literacy")


def test_digital_literacy_graph_covers_all_declared_chapters_and_has_evidence() -> None:
    course = _digital_literacy_course()
    graph = get_knowledge_map(course)

    assert {chapter.chapter for chapter in graph.chapters} == {f"第{index}章" for index in range(1, 9)}
    kc_nodes = [node for node in graph.nodes if node.node_type.value == "kc"]
    assert len(kc_nodes) == 208
    assert all(
        node.learning_points and node.learning_points[0].sources for node in graph.nodes if node.node_type.value == "kc"
    )
    assert all("典型应用" not in node.display_name for node in kc_nodes)
    assert all("案例" not in node.display_name for node in kc_nodes)
    semantic_edges = [edge for edge in graph.edges if edge.relation_type.value != "part_of"]
    assert {edge.relation_type.value for edge in semantic_edges} == {
        "prerequisite_of",
        "related_to",
        "confusable_with",
    }
    assert all(edge.rationale for edge in semantic_edges)
    assert course.revision != course.index_binding.revision


def test_digital_literacy_semantic_relations_cover_each_chapter_without_conflicting_pairs() -> None:
    graph = get_knowledge_map(_digital_literacy_course())
    nodes = {node.canonical_id: node for node in graph.nodes if node.node_type.value == "kc"}
    semantic = [edge for edge in graph.edges if edge.relation_type.value != "part_of"]
    degree = Counter(endpoint for edge in semantic for endpoint in (edge.source, edge.target))

    # Chapter membership is not semantic coverage: every KC needs a teaching connection.
    assert not set(nodes).difference(degree)
    for chapter in graph.chapters:
        chapter_ids = {cid for cid, node in nodes.items() if node.chapter == chapter.chapter}
        assert chapter_ids
        assert all(degree[cid] > 0 for cid in chapter_ids)
        assert any(edge.source in chapter_ids and edge.target in chapter_ids for edge in semantic)

    pairs = [tuple(sorted((edge.source, edge.target))) for edge in semantic]
    assert len(pairs) == len(set(pairs))
    assert all(edge.source in nodes and edge.target in nodes and edge.source != edge.target for edge in semantic)
    assert all(edge.rationale.strip() for edge in semantic)
    assert any(nodes[edge.source].chapter != nodes[edge.target].chapter for edge in semantic)

    # The raw adjacency is exactly the related_to projection, not a second relation taxonomy.
    expected_related: dict[str, set[str]] = {cid: set() for cid in nodes}
    for edge in semantic:
        if edge.relation_type.value == "related_to":
            expected_related[edge.source].add(edge.target)
            expected_related[edge.target].add(edge.source)
    assert all(set(node.related_concepts) == expected_related[cid] for cid, node in nodes.items())

    raw = json.loads((PROJECT_ROOT / "data/courses/digital-literacy/knowledge_graph.json").read_text())
    raw_pairs = [tuple(sorted((edge["source"], edge["target"]))) for edge in raw["relations"]]
    assert len(raw_pairs) == len(set(raw_pairs))
    assert set(raw_pairs) == set(pairs)  # Loader must deduplicate the related_concepts projection.


def test_digital_literacy_prerequisites_follow_mechanisms_and_form_a_dag() -> None:
    graph = get_knowledge_map(_digital_literacy_course())
    prerequisites = {
        (edge.source, edge.target) for edge in graph.edges if edge.relation_type.value == "prerequisite_of"
    }
    required = {
        ("dl_5_3_1_2", "dl_5_6_1_1"),  # Sensor acquisition before real-time digital-twin mapping.
        ("dl_5_4_3_2", "dl_5_4_4_1"),  # Neural-network learning before generative training.
        ("dl_5_8_1_1", "dl_5_8_2_1"),  # Events/probability before conditional-probability calculation.
        ("dl_6_2_1_1", "dl_6_2_2"),  # Security objectives before selecting data-protection controls.
        ("dl_3_3_1_1", "dl_3_3_2"),  # Video properties before diagnosing playback quality.
    }
    assert required <= prerequisites
    assert not {(target, source) for source, target in required}.intersection(prerequisites)
    assert ("dl_2_2_2", "dl_2_3_1") not in prerequisites  # Source quality is not retrieval mechanics.
    assert ("dl_8_2_1", "dl_8_2_3") not in prerequisites  # Chapter order is not a prerequisite.
    assert ("dl_6_3_2_1", "dl_6_3_5_1") not in prerequisites  # QR risk is not a consent-law definition.
    assert ("dl_2_3_1", "dl_2_3_2") not in prerequisites  # Helpful model knowledge is not mandatory tool training.
    assert ("dl_3_2_1_1", "dl_3_2_2") not in prerequisites  # Basic editing need not await representation theory.
    sorter = TopologicalSorter()
    for source, target in prerequisites:
        sorter.add(target, source)
    assert tuple(sorter.static_order())
    assert any(
        edge.relation_type.value == "confusable_with"
        and {edge.source, edge.target} == {"dl_5_9_1", "dl_5_9_2"}
        and "真实" in edge.rationale
        for edge in graph.edges
    )


def test_digital_literacy_corrected_concepts_have_precise_textbook_evidence() -> None:
    nodes = {node.canonical_id: node for node in get_knowledge_map(_digital_literacy_course()).nodes}
    four_layers = nodes["dl_5_3_1_1"]
    assert all(layer in four_layers.display_name for layer in ("感知", "网络", "运算", "应用", "四层"))
    assert "运算层" in four_layers.summary
    assert "四层" in four_layers.learning_points[0].objective

    # These excerpts identify the actual mechanism and its exact textbook/PDF page,
    # rather than accepting a nearby paragraph from the same section as evidence.
    expected_sources = {
        "dl_5_3_1_1": [(130, 146, "感知层、网络层、运算层、应用层"), (131, 147, "数据存储、管理和分析平台")],
        "dl_2_2_3_1": [(41, 57, "检索、浏览、创建、复制、移动和删除")],
        "dl_4_4_1_1": [(117, 133, "验证个人进行各种在线数字活动时的身份"), (116, 132, "实名用户")],
        "dl_6_2_2_1": [
            (214, 230, "与原始数据分开存储"),
            (214, 230, "另一个节点可以接管其任务"),
            (215, 231, "密文方式存储"),
        ],
        "dl_6_3_5_1": [(218, 234, "诈骗分子通过二维码渠道获得我们的身份信息")],
        "dl_6_4_2_1": [(222, 238, '"信息茧房"是指'), (222, 238, "加重群体极化")],
    }
    for cid, expected in expected_sources.items():
        point = nodes[cid].learning_points[0]
        assert point.title == nodes[cid].display_name
        assert point.objective and point.question
        assert len(point.sources) == len(expected)
        for evidence, (book_page, source_page, text) in zip(point.sources, expected, strict=True):
            assert evidence.book_page == book_page
            assert evidence.source_page == source_page
            assert text in evidence.quote

    assert "备份、容错与加密" in nodes["dl_6_2_2_1"].display_name
    assert "扫码" in nodes["dl_6_3_5_1"].learning_points[0].question
    assert "群体极化" in nodes["dl_6_4_2_1"].learning_points[0].objective
    for cid, unsupported in {
        "dl_4_4_1_1": ("多因素",),
        "dl_6_2_2_1": ("数据脱敏", "访问控制与数据脱敏"),
        "dl_6_3_5_1": ("最小必要", "单独同意"),
        "dl_6_4_2_1": ("网络欺凌与沉迷风险应对",),
    }.items():
        assert all(term not in alias for alias in nodes[cid].aliases for term in unsupported)


def test_blockchain_copyright_application_connects_licensing_and_legal_protection() -> None:
    graph = get_knowledge_map(_digital_literacy_course())
    application = next(node for node in graph.nodes if node.canonical_id == "dl_5_5_2_1")
    copyright_evidence = next(
        source for source in application.learning_points[0].sources if "数字版权全生命周期管理" in source.quote
    )
    assert (copyright_evidence.book_page, copyright_evidence.source_page) == (150, 166)
    assert "鉴权" in copyright_evidence.quote and "确权" in copyright_evidence.quote
    assert "司法取证" in copyright_evidence.quote
    for target in ("dl_4_3_1", "dl_8_2_2"):
        edge = next(edge for edge in graph.edges if {edge.source, edge.target} == {"dl_5_5_2_1", target})
        assert edge.relation_type.value == "related_to"
        assert "版权" in edge.rationale
        assert "确权" in edge.rationale or "取证" in edge.rationale


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("信息茧房是什么", "dl_6_4_2_1"),
        ("数据库加密是什么", "dl_6_2_2_1"),
        ("二维码收集个人信息风险是什么", "dl_6_3_5_1"),
        ("政务平台实名注册是什么", "dl_4_4_1_1"),
        ("物联网四层架构是什么", "dl_5_3_1_1"),
        ("Windows资源管理器是什么", "dl_2_2_3_1"),
        ("DIKW是什么", "dl_2_1_2"),
        ("DIKW体系是什么", "dl_2_1_2"),
    ],
)
def test_corrected_course_terms_match_without_embeddings(question: str, expected: str) -> None:
    matches = get_knowledge_mapper("digital-literacy").match_question_rules(question)
    assert matches and matches[0].concept_id == expected


@pytest.mark.parametrize(
    ("question", "incorrect_id"),
    [
        ("多因素身份认证是什么", "dl_4_4_1_1"),
        ("访问控制与数据脱敏是什么", "dl_6_2_2_1"),
        ("最小必要与单独同意原则是什么", "dl_6_3_5_1"),
        ("网络欺凌与沉迷风险应对是什么", "dl_6_4_2_1"),
    ],
)
def test_removed_unsupported_aliases_do_not_force_wrong_course_concepts(question: str, incorrect_id: str) -> None:
    matches = get_knowledge_mapper("digital-literacy").match_question_rules(question)
    assert incorrect_id not in {match.concept_id for match in matches}


def test_digital_literacy_related_projection_serves_mapper_and_concept_detail() -> None:
    mapper = get_knowledge_mapper("digital-literacy")
    related_ids = set(mapper.get_related_concept_ids("dl_5_4_4"))
    assert "dl_5_4_5_1" in related_ids
    assert all(mapper.graph.get_concept(cid) is not None for cid in related_ids)
    assert "大模型应用中的幻觉与偏差" in mapper.get_related_concepts("dl_5_4_4")

    detail = asyncio.run(get_concept_detail("dl_5_4_4", course_id="digital-literacy"))
    assert {related.concept_id for related in detail.related_concepts} == related_ids
    assert all(related.display_name for related in detail.related_concepts)


def test_digital_literacy_course_revision_tracks_graph_without_rebinding_index() -> None:
    course = _digital_literacy_course()
    graph_path = PROJECT_ROOT / course.knowledge_graph_path
    assert course.revision == hashlib.sha256(graph_path.read_bytes()).hexdigest()
    assert course.index_binding.revision == "64549a24cefdd4c934c16d3bdc7fcb92b1d76d16b6754dd4f1bb94f7a6a40f41"


def test_digital_literacy_mapper_and_assessment_target_do_not_use_default_catalog() -> None:
    course = _digital_literacy_course()
    mapper = get_knowledge_mapper("digital-literacy")

    matches = map_question_to_concepts("什么是 AIGC？", course=course)
    assert matches
    assert matches[0].concept_id == "dl_5_4_4"
    assert all(match.concept_id.startswith("dl_") for match in matches)

    target = resolve_target(
        GenerateQuestionsRequest(target_kc_id="dl_5_4_4", count=1),
        course_id="digital-literacy",
    )
    assert target.name == "AIGC、生成式人工智能与大语言模型"
    assert target.chapter == "第5章"
    assert mapper.graph.get_concept("data_science_definition") is None


def test_digital_literacy_prompt_uses_course_identity() -> None:
    prompt = get_system_prompt(_digital_literacy_course())

    assert "《数字素养与技能导论》" in prompt
    assert "《数据科学导论》" not in prompt
