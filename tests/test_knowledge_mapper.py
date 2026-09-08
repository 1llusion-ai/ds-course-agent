"""
Knowledge Mapper 回归测试
用真实学生问题验证三层映射策略
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.teaching.knowledge_mapper import (
    AliasMatchMode,
    ConceptMatchStrength,
    KnowledgeGraph,
    KnowledgeMapper,
    map_question_to_concepts,
)

QUESTION_CASES = [
    ("什么是支持向量机？", ["svm"], "display_name 精确匹配"),
    ("SVM是什么？", ["svm"], "别名精确匹配"),
    ("核函数怎么选？", ["svm_kernel"], "核函数别名匹配"),
    ("kernel trick是什么？", ["svm_kernel"], "英文别名匹配"),
    ("SVM的核函数怎么选择？", ["svm_kernel"], "正则规则: SVM.*核"),
    ("支持向量机里的核技巧怎么用？", ["svm_kernel"], "正则规则: 支持向量机.*核"),
    ("过拟合怎么处理？", ["overfitting"], "正则规则: 过拟合.*怎么"),
    ("模型泛化能力差怎么办？", ["overfitting"], "正则规则: 泛化.*差"),
    ("梯度下降的学习率怎么调？", ["gradient_descent"], "正则规则: 梯度下降.*怎么"),
    ("交叉验证怎么做？", ["cross_validation"], "正则规则: 交叉验证.*怎么"),
    ("决策树剪枝的方法？", ["decision_tree"], "正则规则: 决策树.*剪枝"),
    ("L1正则和L2正则的区别？", ["regularization"], "正则规则: L1正则|L2正则"),
    ("SVM里的那个核是什么原理？", ["svm_kernel"], "需要embedding匹配到核函数"),
    ("怎么防止模型在训练集上记住数据？", ["overfitting"], "语义匹配到"),
    ("我想让模型在没见过数据上表现好", ["overfitting", "cross_validation"], "语义匹配泛化/验证概念"),
    ("神经网络和SVM哪个好？", ["svm", "neural_network"], "多概念，SVM应被识别"),
    ("Python里怎么实现核函数？", ["svm_kernel"], "可能误判为代码实现而非概念"),
    ("什么是核技巧？kernel function的原理？", ["svm_kernel"], "中英混合，应识别"),
    ("数据清洗怎么做？", ["data_cleaning"], "基础概念，应精确匹配"),
    ("过拟合和欠拟合的区别？", ["overfitting"], "概念对比，应识别过拟合"),
]


@pytest.mark.parametrize(
    ("question", "expected_ids", "note"),
    QUESTION_CASES,
    ids=[case[0] for case in QUESTION_CASES],
)
def test_question_mapping(question, expected_ids, note):
    matches = map_question_to_concepts(question, top_k=3)
    actual_ids = [m.concept_id for m in matches]
    for expected_id in expected_ids:
        assert expected_id in actual_ids, f"{note}: {question} -> {actual_ids}"


def run_regression_test():
    """运行回归测试"""
    test_cases = QUESTION_CASES

    print("=" * 80)
    print("Knowledge Mapper 回归测试")
    print("=" * 80)

    passed = 0
    failed = 0
    warnings = 0

    for question, expected_ids, note in test_cases:
        print(f"\n[测试] {question}")
        print(f"      备注: {note}")
        print(f"      期望: {expected_ids}")

        matches = map_question_to_concepts(question, top_k=3)
        actual_ids = [m.concept_id for m in matches]
        print(f"      实际: {actual_ids}")

        # 检查期望的概念是否在结果中
        missing = []
        for expected_id in expected_ids:
            if expected_id not in actual_ids:
                missing.append(expected_id)

        if not missing:
            print("      [OK] 通过")
            passed += 1
        else:
            print(f"      [FAIL] 失败 - 缺失: {missing}")
            failed += 1

        # 额外检查：显示匹配方法和分数
        for m in matches:
            marker = "[Y]" if m.concept_id in expected_ids else "[N]"
            print(f"         {marker} {m.concept_id}: {m.method} ({m.score})")

    print("\n" + "=" * 80)
    print(f"测试结果: 通过 {passed}/{len(test_cases)}, 失败 {failed}, 警告 {warnings}")
    print("=" * 80)

    return failed == 0


def test_edge_cases():
    """边界情况测试"""
    print("\n" + "=" * 80)
    print("边界情况测试")
    print("=" * 80)

    edge_cases = [
        ("", "空字符串"),
        ("12345", "无意义数字"),
        ("今天天气怎么样", "完全无关问题"),
        ("SVM SVM SVM 核函数 核函数", "重复关键词"),
        ("什么是什么是支持向量机机机？", "错别字/重复字"),
    ]

    for question, note in edge_cases:
        print(f"\n[边界] {note}: '{question}'")
        matches = map_question_to_concepts(question, top_k=3)
        if matches:
            print(f"      匹配到: {[(m.concept_id, m.method, m.score) for m in matches]}")
        else:
            print("      未匹配到任何概念（符合预期）")


def test_ascii_alias_uses_token_boundaries(monkeypatch):
    """ASCII 别名只能按完整 token 命中，不能匹配其他单词内部。"""
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    mapper = KnowledgeMapper()

    for question in ("你的 loop 有几轮？", "for loop 怎么写？", "用 while-loop 实现"):
        matches = mapper.map_question(question)
        assert "object_oriented_programming" not in {match.concept_id for match in matches}

    matches = mapper.map_question("OOP 是什么？")
    oop_match = next(match for match in matches if match.concept_id == "object_oriented_programming")
    assert oop_match.method == "exact_alias"
    assert oop_match.match_strength is ConceptMatchStrength.STRONG
    assert oop_match.routing_eligible is True


def test_contextual_alias_policy_does_not_emit_independent_match(monkeypatch):
    """宽泛 contextual 别名保留在公开 aliases 中，但不能单独生成知识点。"""
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    graph = KnowledgeGraph()
    mapper = KnowledgeMapper(graph=graph)

    for alias in ("分类", "模型", "训练"):
        policy = graph.alias_policies[alias]
        assert policy.match_mode is AliasMatchMode.CONTEXTUAL
        assert policy.match_strength is ConceptMatchStrength.SUPPORTING
    assert "分类" in graph.get_concept("logistic_regression")["aliases"]

    for question in ("分类", "任务分类", "这个任务怎么分类？"):
        matches = mapper.map_question(question)
        assert "logistic_regression" not in {match.concept_id for match in matches}

    matches = mapper.map_question("分类问题能用逻辑回归吗？")
    logistic_match = next(match for match in matches if match.concept_id == "logistic_regression")
    assert logistic_match.match_strength is ConceptMatchStrength.STRONG
    assert logistic_match.routing_eligible is True


def test_regex_and_embedding_matches_expose_routing_strength(monkeypatch):
    """正则命中可驱动路由，Embedding 只提供 supporting 语义信号。"""
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    mapper = KnowledgeMapper()
    regex_matches = mapper.map_question("支持向量机该怎么选择核？")
    regex_match = next(match for match in regex_matches if match.concept_id == "svm_kernel")

    assert regex_match.method == "regex_rule"
    assert regex_match.match_strength is ConceptMatchStrength.STRONG
    assert regex_match.routing_eligible is True

    class FakeGraph:
        alias_specs = {}
        regex_rules = []
        embeddings = {
            "overfitting": np.array([1.0, 0.0]),
        }

        def _normalize_text(self, text):
            return text

        def get_concept(self, concept_id):
            return {
                "display_name": concept_id,
                "chapter": "unit",
            }

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first")
    embedding_mapper = KnowledgeMapper(graph=FakeGraph())
    monkeypatch.setattr(embedding_mapper, "_embed_text", lambda text: np.array([1.0, 0.0]))

    embedding_match = embedding_mapper.map_question(
        "没有规则命中的语义问题",
        top_k=1,
        embedding_threshold=0.8,
    )[0]
    assert embedding_match.method == "embedding"
    assert embedding_match.match_strength is ConceptMatchStrength.SUPPORTING
    assert embedding_match.routing_eligible is False


def test_rule_match_skips_query_embedding(monkeypatch):
    """高置信规则/别名命中后不再在线 query embedding 补满 top_k。"""
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first")
    monkeypatch.setattr(config, "CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH", True)
    monkeypatch.setattr(config, "CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP", 1)

    mapper = KnowledgeMapper()

    def fail_if_called(text):
        raise AssertionError("query embedding should be skipped after rule hit")

    monkeypatch.setattr(mapper, "_embed_text", fail_if_called)

    token = begin_query_trace({"entrypoint": "unit_test"})
    matches = mapper.map_question("什么是支持向量机？", top_k=3)
    trace = end_query_trace(token)

    assert matches
    assert matches[0].concept_id == "svm"
    assert any(
        event["stage"] == "concept_map.embedding_skipped" and event["data"]["reason"] == "rule_match"
        for event in trace["events"]
    )


def test_embedding_fallback_uses_offline_cache_only_when_rules_miss(monkeypatch):
    """规则没命中时才用离线概念向量 + 短超时 query embedding 兜底。"""
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first")
    monkeypatch.setattr(config, "CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH", True)

    class FakeGraph:
        alias_specs = {}
        regex_rules = []
        embeddings = {
            "overfitting": np.array([1.0, 0.0]),
            "svm": np.array([0.0, 1.0]),
        }

        def _normalize_text(self, text):
            return text

        def get_concept(self, concept_id):
            return {
                "display_name": concept_id,
                "chapter": "unit",
            }

    mapper = KnowledgeMapper(graph=FakeGraph())
    monkeypatch.setattr(mapper, "_embed_text", lambda text: np.array([1.0, 0.0]))

    matches = mapper.map_question("语义上指向泛化变差但没有显式别名", top_k=1, embedding_threshold=0.8)

    assert [(match.concept_id, match.method) for match in matches] == [("overfitting", "embedding")]


def test_knowledge_graph_does_not_online_precompute_without_cache(tmp_path, monkeypatch):
    """请求路径默认只加载离线 cache；cache 缺失时不在线预计算概念 embedding。"""
    import ds_course_agent.shared.config as config
    import ds_course_agent.teaching.knowledge_mapper as knowledge_mapper

    graph_path = tmp_path / "knowledge_graph.json"
    graph_path.write_text(
        """
        {
          "concepts": [
            {
              "canonical_id": "unit_concept",
              "display_name": "单元概念",
              "chapter": "unit",
              "aliases": ["单元概念"],
              "related_concepts": []
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    missing_cache = tmp_path / "missing_embeddings.json"

    monkeypatch.setenv("KNOWLEDGE_MAPPER_EMBEDDING_CACHE", str(missing_cache))
    monkeypatch.setattr(config, "CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED", False)
    monkeypatch.setattr(
        knowledge_mapper,
        "create_embedding_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not create online model")),
    )

    graph = KnowledgeGraph(graph_path=str(graph_path))

    assert graph.embeddings == {}


if __name__ == "__main__":
    success = run_regression_test()
    test_edge_cases()

    sys.exit(0 if success else 1)
