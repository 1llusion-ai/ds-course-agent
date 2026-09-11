"""Course graph integrity and conservative learner-state projection contracts."""

from __future__ import annotations

import json
from collections import Counter
from graphlib import CycleError

import pytest
from pydantic import ValidationError

from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.knowledge_map import (
    LearningState,
    NodeType,
    get_knowledge_map,
    load_knowledge_map,
    overlay_learning_state,
)
from ds_course_agent.teaching.knowledge_mapper import KnowledgeGraph, KnowledgeMapper
from ds_course_agent.teaching.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

CATALOG = PROJECT_ROOT / "data/knowledge_graph.json"
TOC = PROJECT_ROOT / "data/目录.json"


def test_concept_graph_has_closed_curated_relations_and_keeps_sourced_references():
    graph = get_knowledge_map()
    nodes = {node.canonical_id: node for node in graph.nodes}
    components = [node for node in graph.nodes if node.node_type is NodeType.KC]
    assert len(graph.chapters) == 10
    assert len(components) == 128
    assert graph.version == "1.6"
    assert "dataframe_create" not in nodes
    assert "pandas_fillna" not in nodes
    assert "opencv_image_io" not in nodes
    assert "algorithm_analysis_report" not in nodes
    assert "defense_report" not in nodes
    assert "anaconda" not in nodes
    assert "pycharm" not in nodes
    assert "mnist" not in nodes
    assert "food_image_project" not in nodes
    assert "llm_examples" not in nodes
    assert "writing_assistant" not in nodes
    assert "literature_reading_assistant" not in nodes
    assert "financial_service_assistant" not in nodes
    assert not {
        "kaggle",
        "drivendata",
        "tianchi",
        "datacastle",
        "datafountain",
        "chinavis",
        "modelwhale",
    }.intersection(nodes)
    assert nodes["opencv"].node_type is NodeType.KC
    assert nodes["dataframe"].display_name == "DataFrame"
    assert any(point.title == "从字典创建 DataFrame" for point in nodes["dataframe"].learning_points)
    for node in components:
        assert nodes[node.parent_id].node_type is NodeType.CHAPTER
        for point in node.learning_points:
            assert point.objective and point.question and point.sources
            assert all(52 <= source.book_page <= 74 for source in point.sources)
    for edge in graph.edges:
        assert edge.source in nodes and edge.target in nodes
    assert Counter(edge.relation_type.value for edge in graph.edges) == {
        "part_of": 128,
        "related_to": 86,
        "prerequisite_of": 103,
        "confusable_with": 16,
    }
    semantic_pairs = [
        tuple(sorted((edge.source, edge.target))) for edge in graph.edges if edge.relation_type.value != "part_of"
    ]
    assert len(semantic_pairs) == len(set(semantic_pairs))
    semantic_degree = Counter(
        endpoint
        for edge in graph.edges
        if edge.relation_type.value != "part_of"
        for endpoint in (edge.source, edge.target)
    )
    assert all(semantic_degree[node.canonical_id] > 0 for node in components)
    assert all(related in nodes for node in components for related in node.related_concepts)
    assert all(
        node.canonical_id in nodes[related].related_concepts for node in components for related in node.related_concepts
    )
    assert nodes["data_science_definition"].display_name == "数据科学"
    assert nodes["loc_iloc"].display_name == "标签索引与位置索引"
    assert nodes["deep_learning_frameworks"].display_name == "深度学习框架"
    assert "算法分析报告" in nodes["competition_workflow"].aliases
    assert "答辩报告" in nodes["competition_workflow"].aliases
    assert "PyCharm" in nodes["python_ide"].aliases
    assert "MNIST手写数字识别" in nodes["lenet5"].aliases
    assert "美食图鉴项目" in nodes["convolutional_neural_network"].aliases
    assert "ChatGPT" in nodes["large_language_model"].aliases
    assert nodes["large_language_model_applications"].display_name == "大语言模型应用"
    assert nodes["competition_platforms"].display_name == "数据科学竞赛平台"
    assert len({(edge.source, edge.target, edge.relation_type) for edge in graph.edges}) == len(graph.edges)


@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate",
        "missing_source",
        "unknown_endpoint",
        "unknown_related",
        "asymmetric_related",
        "cycle",
        "invalid_parent",
        "unknown_chapter",
        "semantic_conflict",
    ],
)
def test_catalog_rejects_invalid_graph_contracts(tmp_path, corruption):
    raw = json.loads(CATALOG.read_text())
    kc = next(item for item in raw["concepts"] if item.get("learning_points"))
    if corruption == "duplicate":
        raw["concepts"].append(raw["concepts"][0])
    elif corruption == "missing_source":
        kc["learning_points"][0]["sources"] = []
    elif corruption == "unknown_endpoint":
        raw["relations"][0]["target"] = "not_a_course_node"
    elif corruption == "unknown_related":
        raw["concepts"][0]["related_concepts"].append("not_a_course_node")
    elif corruption == "asymmetric_related":
        related_id = raw["concepts"][0]["related_concepts"][0]
        related = next(item for item in raw["concepts"] if item["canonical_id"] == related_id)
        related["related_concepts"].remove(raw["concepts"][0]["canonical_id"])
    elif corruption == "cycle":
        edge = raw["relations"][0]
        raw["relations"].append({**edge, "source": edge["target"], "target": edge["source"]})
    elif corruption == "semantic_conflict":
        edge = raw["relations"][0]
        relation_type = "confusable_with" if edge["relation_type"] != "confusable_with" else "related_to"
        raw["relations"].append({"source": edge["source"], "target": edge["target"], "relation_type": relation_type})
    elif corruption == "unknown_chapter":
        kc["chapter"] = "第99章"
    else:
        kc["parent_id"] = "dataframe"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(raw))
    with pytest.raises((ValueError, ValidationError, CycleError)):
        load_knowledge_map(path, TOC)


def test_related_concept_history_never_propagates_or_leaks_to_another_student():
    graph = get_knowledge_map()
    profile = StudentProfile(student_id="alice")
    profile.resolved_weak_spots.append(WeakSpotCandidate(concept_id="opencv", display_name="OpenCV"))
    profile.recent_concepts["dataframe"] = ConceptFocus(
        concept_id="dataframe", display_name="DataFrame", chapter="第4章", mention_count=50
    )
    alice = {node.canonical_id: node for node in overlay_learning_state(graph, profile).nodes}
    assert alice["opencv"].learning_state is LearningState.RESOLVED
    assert alice["image_transformation"].learning_state is LearningState.UNOBSERVED
    assert alice["dataframe"].learning_state is LearningState.RECENT
    bob = overlay_learning_state(graph, StudentProfile(student_id="bob"))
    assert all(node.learning_state is LearningState.UNOBSERVED for node in bob.nodes)
    assert all(node.learning_state is LearningState.UNOBSERVED for node in graph.nodes)
    assert len(profile.resolved_weak_spots) == 1


def test_active_difficulty_takes_precedence_over_resolved_history():
    profile = StudentProfile(student_id="alice")
    spot = WeakSpotCandidate(concept_id="dataframe", display_name="DataFrame")
    profile.resolved_weak_spots.append(spot)
    profile.weak_spot_candidates.append(spot)
    result = overlay_learning_state(get_knowledge_map(), profile)
    assert (
        next(node for node in result.nodes if node.canonical_id == spot.concept_id).learning_state
        is LearningState.NEEDS_REVIEW
    )


@pytest.mark.parametrize(
    "question,expected",
    [
        ("从字典创建 DataFrame", "dataframe"),
        ("cv2.imread如何读取图像？", "opencv"),
        ("iloc怎么选第四行？", "loc_iloc"),
        ("loc 如何按行标签选数据？", "loc_iloc"),
        ("loc索引怎么写？", "loc_iloc"),
        ("基于标签选择数据", "loc_iloc"),
        ("基于位置选择数据", "loc_iloc"),
        ("fillna怎么填充空值？", "missing_values"),
        ("fillna(0)有什么用？", "missing_values"),
        ("ignore_index=True有什么用？", "data_merge"),
        ("StandardScaler为什么只在训练集上拟合？", "feature_standardization"),
        ("cv2.Canny双阈值是什么意思？", "edge_detection"),
        ("缺失值处理", "missing_values"),
        ("算法分析报告应该包含什么？", "competition_workflow"),
        ("答辩报告怎么准备？", "competition_workflow"),
        ("PyCharm 怎么配置？", "python_ide"),
        ("MNIST 手写数字识别", "lenet5"),
        ("美食图鉴项目", "convolutional_neural_network"),
        ("ChatGPT 是什么类型的产品？", "large_language_model"),
        ("怎样用大模型辅助阅读文献？", "large_language_model_applications"),
        ("Kaggle 和天池属于什么平台？", "competition_platforms"),
        ("深度学习不是机器学习的一种", "neural_network"),
    ],
)
def test_new_components_use_existing_mapper_without_online_embedding(monkeypatch, question, expected):
    def unexpected_embedding(*args, **kwargs):
        pytest.fail("An explicit KC query must not require online embeddings")

    monkeypatch.setattr(KnowledgeMapper, "_embed_text", unexpected_embedding)
    mapper = KnowledgeMapper(KnowledgeGraph())
    matches = mapper.map_question(question)
    assert matches[0].concept_id == expected
    assert matches[0].event_eligible
    if expected == "missing_values":
        assert all(not match.concept_id.startswith("pandas_") for match in matches)


def test_every_display_name_maps_to_its_canonical_concept_without_embedding(monkeypatch):
    def unexpected_embedding(*args, **kwargs):
        pytest.fail("A display-name query must not require online embeddings")

    monkeypatch.setattr(KnowledgeMapper, "_embed_text", unexpected_embedding)
    mapper = KnowledgeMapper(KnowledgeGraph())
    for concept_id, concept in mapper.graph.concepts.items():
        matches = mapper.map_question(concept["display_name"], top_k=10)
        assert concept_id in {match.concept_id for match in matches}, concept["display_name"]


def test_specific_concept_suppresses_only_the_overlapping_generic_match(monkeypatch):
    monkeypatch.setattr("ds_course_agent.shared.config.CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    mapper = KnowledgeMapper(KnowledgeGraph())

    history = mapper.map_question("数据科学的发展历程", top_k=10)
    assert [(match.concept_id, match.event_eligible) for match in history] == [("data_science_history", True)]

    comparison = mapper.map_question("神经网络和卷积神经网络有什么区别？", top_k=10)
    assert {match.concept_id for match in comparison} >= {"neural_network", "convolutional_neural_network"}


def test_chinese_punctuation_does_not_make_alias_matching_depend_on_embedding(monkeypatch):
    monkeypatch.setattr("ds_course_agent.shared.config.CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    mapper = KnowledgeMapper(KnowledgeGraph())

    matches = mapper.map_question("数据、思维")
    assert [(match.concept_id, match.method) for match in matches] == [("data_thinking", "exact_alias")]


def test_shared_alias_maps_to_each_declared_concept_without_catalog_ordering(monkeypatch):
    def unexpected_embedding(*args, **kwargs):
        pytest.fail("A declared alias must not require online embeddings")

    monkeypatch.setattr(KnowledgeMapper, "_embed_text", unexpected_embedding)
    mapper = KnowledgeMapper(KnowledgeGraph())
    matches = mapper.map_question("在没见过数据上表现好", top_k=10)
    assert {"cross_validation", "overfitting"} <= {match.concept_id for match in matches}


def test_mapper_resolves_canonical_related_ids_to_display_names():
    mapper = KnowledgeMapper(KnowledgeGraph())
    related = mapper.get_related_concepts("dataframe")
    assert "结构化数据" in related
    assert "Python数据类型" in related
    assert "structured_data" not in related
    assert all(item in {concept["display_name"] for concept in mapper.graph.concepts.values()} for item in related)
