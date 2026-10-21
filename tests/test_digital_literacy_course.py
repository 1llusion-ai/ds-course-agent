"""Digital-literacy resource and teaching-boundary regressions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from graphlib import TopologicalSorter

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
        ("dl_6_3_2_1", "dl_6_3_5_1"),  # Identify sensitive data before applying stricter consent.
        ("dl_3_3_1_1", "dl_3_3_2"),  # Video properties before diagnosing playback quality.
    }
    assert required <= prerequisites
    assert not {(target, source) for source, target in required}.intersection(prerequisites)
    assert ("dl_2_2_2", "dl_2_3_1") not in prerequisites  # Source quality is not retrieval mechanics.
    assert ("dl_8_2_1", "dl_8_2_3") not in prerequisites  # Chapter order is not a prerequisite.
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
