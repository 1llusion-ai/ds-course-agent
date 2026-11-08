"""AI-literacy textbook evidence, graph semantics, and course identity contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from graphlib import TopologicalSorter

import pytest

from ds_course_agent.agent.prompt import get_system_prompt
from ds_course_agent.courses import CourseCatalog
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.knowledge_map import get_knowledge_map, load_knowledge_map
from ds_course_agent.teaching.knowledge_mapper import KnowledgeGraph, KnowledgeMapper

COURSE_ID = "ai-literacy"
GRAPH_PATH = PROJECT_ROOT / "data/courses/ai-literacy/knowledge_graph.json"
TOC_PATH = PROJECT_ROOT / "data/courses/ai-literacy/toc.json"
MARKER_PATH = PROJECT_ROOT / "var/artifacts/ai-literacy-onboarding/marker_intermediate.json"


def _raw_graph():
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _course():
    return CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(COURSE_ID)


@pytest.fixture
def mapper(monkeypatch):
    # Concept identity tests must neither load another course's vectors nor
    # initialize an online embedding client, regardless of developer settings.
    monkeypatch.setenv("KNOWLEDGE_MAPPER_DISABLE_ONLINE_EMBEDDINGS", "1")
    monkeypatch.setattr(KnowledgeGraph, "_precompute_embeddings", lambda self: None)
    return KnowledgeMapper(KnowledgeGraph(str(GRAPH_PATH)))


def test_ai_literacy_graph_has_body_kcs_in_every_declared_chapter():
    graph = load_knowledge_map(GRAPH_PATH, TOC_PATH)
    raw = _raw_graph()
    chapters = {f"第{number}章" for number in range(1, 9)}
    assert graph.course_name == "人工智能通识"
    assert {chapter.chapter for chapter in graph.chapters} == chapters
    assert {node.chapter for node in graph.nodes if node.node_type.value == "kc"} == chapters
    assert all(chapter.kc_count > 0 for chapter in graph.chapters)
    assert {node.canonical_id for node in graph.nodes if node.node_type.value == "chapter"} == {
        f"chapter:{number}" for number in range(1, 9)
    }
    assert all(node["canonical_id"].startswith("ai_") for node in raw["concepts"])
    assert all(not node["canonical_id"].startswith("chapter:") for node in raw["concepts"])
    assert len({node["canonical_id"] for node in raw["concepts"]}) == len(raw["concepts"])
    for node in raw["concepts"]:
        assert node["section"].split(".")[0] == re.search(r"\d+", node["chapter"])[0]
        assert node["learning_points"]
        assert all(point["sources"] for point in node["learning_points"])


def test_ai_literacy_all_evidence_pages_fit_the_owned_toc():
    toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
    chapters = {f"第{chapter['number']}章": chapter for chapter in toc["toc"] if chapter.get("kind") == "chapter"}
    assert toc["course_id"] == COURSE_ID
    assert toc["page_offset"] == 0
    assert toc["source"]["path"] == "var/course_sources/ai-literacy/ai-literacy-course.pdf"
    for node in _raw_graph()["concepts"]:
        chapter = chapters[node["chapter"]]
        for point in node["learning_points"]:
            for source in point["sources"]:
                assert source["source_id"] == "ai-literacy-course.pdf"
                assert source["title"] == "人工智能通识教材"
                assert chapter["book_page_start"] <= source["book_page"] <= chapter["book_page_end"]
                assert source["book_page"] == source["source_page"]
                assert 1 <= source["book_page"] <= 250  # Body chapters; appendices/header-only 264 are not KCs.
                assert len(re.sub(r"\s+", "", source["quote"])) >= 35
                assert "digital-literacy" not in source["source_id"]


def test_ai_literacy_every_quote_is_literal_text_on_its_frozen_marker_page():
    if not MARKER_PATH.is_file():
        pytest.skip("local frozen Marker artifact is not included in source-only checkout")
    payload = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    assert payload["file_name"] == "ai-literacy-course.pdf"
    assert payload["total_pages"] == 264
    pages = {page["page_num"]: page["text"] for page in payload["pages"]}
    assert set(pages) == set(range(1, 265))
    for node in _raw_graph()["concepts"]:
        for point in node["learning_points"]:
            for source in point["sources"]:
                assert source["quote"] in pages[source["source_page"]], node["canonical_id"]


@pytest.mark.parametrize(
    ("concept_id", "page", "prose"),
    [
        ("ai_turing", 5, "若审问者无法可靠区分"),
        ("ai_backprop", 48, "从输出层反向传递的误差信号"),
        ("ai_self_attention", 75, "查询、键、值三者均来自同一个序列"),
        ("ai_attention_weights", 75, "权重之和为1"),
        ("ai_bpe", 78, "反复合并频率最高"),
        ("ai_clip", 86, "真正匹配的图像-文本对"),
        ("ai_prompt_engineering", 100, "不改变模型参数"),
        ("ai_prompt_injection", 103, "间接注入"),
        ("ai_rag", 137, "用户的原始问题与检索到的Top-N相关文档"),
        ("ai_recall", 145, "知识库中总相关文档数"),
        ("ai_precision", 145, "检索到的文档中相关文档数"),
        ("ai_chunking", 147, "过小则易引发语义断裂"),
        ("ai_function_call", 168, "并非让模型直接执行代码"),
        ("ai_mcp", 168, "统一大模型与外部数据源、工具之间的连接方式"),
        ("ai_skill", 168, "离散工具组合为完整业务流程"),
        ("ai_embodied", 190, "通过物理载体与环境进行实时交互"),
        ("ai_slam", 193, "确定自身在地图中的位置"),
        ("ai_asr", 229, "语音信号转换为文本"),
        ("ai_tts", 231, "文本转化为自然流畅语音"),
        ("ai_digital_twin", 235, "物理世界与虚拟空间之间的实时同步"),
        ("ai_smart_grid", 245, "电力供需平衡"),
    ],
)
def test_ai_literacy_key_mechanisms_have_precise_body_evidence(concept_id, page, prose):
    nodes = {node["canonical_id"]: node for node in _raw_graph()["concepts"]}
    sources = [source for point in nodes[concept_id]["learning_points"] for source in point["sources"]]
    assert any(source["book_page"] == page and prose in re.sub(r"\s+", "", source["quote"]) for source in sources)


def test_ai_literacy_semantic_relations_cover_kcs_without_conflicting_pairs():
    raw = _raw_graph()
    nodes = {node["canonical_id"]: node for node in raw["concepts"]}
    relations = raw["relations"]
    pairs = [tuple(sorted((edge["source"], edge["target"]))) for edge in relations]
    assert len(pairs) == len(set(pairs))
    assert {edge["relation_type"] for edge in relations} == {"related_to", "prerequisite_of", "confusable_with"}
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in relations)
    assert all(edge["source"] != edge["target"] and edge["rationale"].strip() for edge in relations)
    degree = Counter(endpoint for edge in relations for endpoint in (edge["source"], edge["target"]))
    assert set(nodes) == set(degree)
    for chapter in {node["chapter"] for node in nodes.values()}:
        chapter_ids = {key for key, node in nodes.items() if node["chapter"] == chapter}
        assert any(edge["source"] in chapter_ids and edge["target"] in chapter_ids for edge in relations)
    assert any(nodes[edge["source"]]["chapter"] != nodes[edge["target"]]["chapter"] for edge in relations)


def test_ai_literacy_related_adjacency_is_exactly_the_bidirectional_relation_projection(mapper):
    raw = _raw_graph()
    expected = {node["canonical_id"]: set() for node in raw["concepts"]}
    for edge in raw["relations"]:
        if edge["relation_type"] == "related_to":
            expected[edge["source"]].add(edge["target"])
            expected[edge["target"]].add(edge["source"])
    for node in raw["concepts"]:
        assert len(node["related_concepts"]) == len(set(node["related_concepts"]))
        assert set(node["related_concepts"]) == expected[node["canonical_id"]]
        assert set(mapper.get_related_concept_ids(node["canonical_id"])) == expected[node["canonical_id"]]
    loaded = load_knowledge_map(GRAPH_PATH, TOC_PATH)
    assert sum(edge.relation_type.value != "part_of" for edge in loaded.edges) == len(raw["relations"])


def test_ai_literacy_prerequisites_are_acyclic_and_follow_mechanisms():
    raw = _raw_graph()
    edges = {
        (edge["source"], edge["target"]) for edge in raw["relations"] if edge["relation_type"] == "prerequisite_of"
    }
    sorter = TopologicalSorter()
    for source, target in edges:
        sorter.add(target, source)
    tuple(sorter.static_order())
    required = {
        ("ai_neuron", "ai_backprop"),
        ("ai_token", "ai_tokenizer"),
        ("ai_self_attention", "ai_transformer"),
        ("ai_pretraining", "ai_finetuning"),
        ("ai_finetuning", "ai_lora"),
        ("ai_embedding", "ai_rag_retrieval"),
        ("ai_chunking", "ai_vector_index"),
        ("ai_driving_fusion", "ai_driving_planning"),
    }
    assert required <= edges
    assert not {(target, source) for source, target in required}.intersection(edges)
    # Shared application context and chapter order are not mandatory learning dependencies.
    assert ("ai_ethics", "ai_pretraining") not in edges
    assert ("ai_prompt_engineering", "ai_finetuning") not in edges
    assert ("ai_gpu", "ai_pretraining") not in edges


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("ai_prompt_engineering", "ai_finetuning"),
        ("ai_function_call", "ai_mcp"),
        ("ai_skill", "ai_function_call"),
        ("ai_agent_loop", "ai_embodied"),
        ("ai_recall", "ai_precision"),
        ("ai_asr", "ai_tts"),
        ("ai_vr", "ai_ar"),
        ("ai_ar", "ai_mr"),
    ],
)
def test_ai_literacy_confusable_pairs_preserve_concrete_boundaries(first, second):
    matches = [
        edge
        for edge in _raw_graph()["relations"]
        if {edge["source"], edge["target"]} == {first, second} and edge["relation_type"] == "confusable_with"
    ]
    assert len(matches) == 1
    assert len(matches[0]["rationale"]) >= 30


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("图灵测试有哪些局限？", "ai_turing"),
        ("Transformer怎样建模序列？", "ai_transformer"),
        ("BPE怎样合并子词？", "ai_bpe"),
        ("CLIP怎样比较图像和文字？", "ai_clip"),
        ("提示工程需要训练参数吗？", "ai_prompt_engineering"),
        ("RAG如何利用检索资料？", "ai_rag"),
        ("函数调用是直接执行代码吗？", "ai_function_call"),
        ("MCP负责什么？", "ai_mcp"),
        ("具身智能为什么需要物理载体？", "ai_embodied"),
        ("SLAM解决什么问题？", "ai_slam"),
        ("语音识别与语音合成有什么不同？", "ai_asr"),
        ("数字孪生如何同步现实状态？", "ai_digital_twin"),
    ],
)
def test_ai_literacy_mapper_routes_real_textbook_terms_without_embeddings(mapper, question, expected):
    matches = mapper.match_question_rules(question)
    assert expected in {match.concept_id for match in matches}
    assert all(match.concept_id in mapper.graph.concepts for match in matches)
    assert mapper.graph.get_concept("data_science_definition") is None
    assert mapper.graph.get_concept("dl_5_4_4") is None


@pytest.mark.parametrize("question", ["paragraph segmentation", "scotland", "adversarialinput", "TTSengine"])
def test_ai_literacy_ascii_aliases_require_token_boundaries(mapper, question):
    assert not mapper.match_question_rules(question)


def test_ai_literacy_prompt_and_map_keep_manifest_identity_without_default_resources():
    manifest = _course()
    graph = get_knowledge_map(manifest)
    assert graph.course_name == manifest.display_name == "人工智能通识"
    prompt = get_system_prompt(manifest)
    assert "《人工智能通识》" in prompt
    assert "《数据科学导论》" not in prompt
    assert "《数字素养与技能导论》" not in prompt
    assert manifest.prompt_path == ""
    assert manifest.course_id == COURSE_ID
    assert manifest.toc_path == TOC_PATH.relative_to(PROJECT_ROOT).as_posix()


def test_ai_literacy_manifest_binds_the_exact_graph_revision_and_an_independent_index():
    manifest = _course()
    assert manifest.knowledge_graph_path == GRAPH_PATH.relative_to(PROJECT_ROOT).as_posix()
    assert manifest.revision == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
    assert manifest.resource_metadata["page_offset"] == 0
    assert manifest.is_ready
    assert manifest.index_binding is not None
    assert manifest.index_binding.persist_directory.startswith("var/chroma_candidates/ai-literacy/")
    assert manifest.index_binding.metadata_schema_version == "retrieval-provenance/1.0"
    others = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").list()
    assert all(
        manifest.index_binding.collection_name != other.index_binding.collection_name
        and manifest.index_binding.persist_directory != other.index_binding.persist_directory
        for other in others
        if other.course_id != COURSE_ID and other.index_binding is not None
    )


def test_ai_literacy_resource_ids_are_independent_of_other_course_graphs():
    ids = {node["canonical_id"] for node in _raw_graph()["concepts"]}
    for course in CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").list():
        if course.course_id != COURSE_ID and course.knowledge_graph_path:
            other = json.loads((PROJECT_ROOT / course.knowledge_graph_path).read_text(encoding="utf-8"))
            assert ids.isdisjoint(node["canonical_id"] for node in other["concepts"])
