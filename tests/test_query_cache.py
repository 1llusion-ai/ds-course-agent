import gc
import time
import weakref

import numpy as np
import pytest

from ds_course_agent.agent.routing import utils
from ds_course_agent.shared import embeddings
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.teaching import knowledge_mapper
from ds_course_agent.teaching.knowledge_mapper import KnowledgeMapper, MatchedConcept


@pytest.fixture(autouse=True)
def clear_concept_map_cache():
    knowledge_mapper.clear_map_question_cache()
    yield
    knowledge_mapper.clear_map_question_cache()


def _minimal_graph(*, embeddings=None):
    graph = knowledge_mapper.KnowledgeGraph.__new__(knowledge_mapper.KnowledgeGraph)
    graph.concepts = {
        "unit": {
            "canonical_id": "unit",
            "display_name": "Unit",
            "chapter": "unit",
            "aliases": [],
        }
    }
    graph.alias_to_concept = {}
    graph.alias_specs = {}
    graph.alias_policies = {}
    graph.regex_rules = []
    graph.embeddings = embeddings or {}
    return graph


def test_map_question_to_concepts_uses_inprocess_cache(monkeypatch):
    knowledge_mapper.clear_map_question_cache()
    monkeypatch.setattr(knowledge_mapper.config, "QUERY_CACHE_ENABLED", True)

    class FakeMapper:
        def __init__(self):
            self.calls = 0

        def map_question(self, question, top_k):
            self.calls += 1
            return [
                MatchedConcept(
                    concept_id="svm",
                    display_name="支持向量机",
                    chapter="第6章",
                    method="exact_alias",
                    score=1.0,
                )
            ]

    fake_mapper = FakeMapper()
    monkeypatch.setattr(knowledge_mapper, "get_knowledge_mapper", lambda: fake_mapper)

    first = knowledge_mapper.map_question_to_concepts("SVM是什么？", top_k=3)
    second = knowledge_mapper.map_question_to_concepts("SVM是什么？", top_k=3)

    assert fake_mapper.calls == 1
    assert [item.concept_id for item in first] == ["svm"]
    assert [item.concept_id for item in second] == ["svm"]
    assert first is not second
    assert first[0] is not second[0]
    assert knowledge_mapper.map_question_cache_info().hits >= 1


def test_concept_map_cache_reuses_equivalent_mapper_configuration(monkeypatch):
    monkeypatch.setattr(knowledge_mapper.config, "QUERY_CACHE_ENABLED", True)
    monkeypatch.setattr(knowledge_mapper.config, "CONCEPT_MAP_EMBEDDING_MODE", "disabled")

    mapper_a = KnowledgeMapper(graph=_minimal_graph())
    mapper_b = KnowledgeMapper(graph=_minimal_graph())
    current_mapper = [mapper_a]
    calls = 0
    original_map_question = KnowledgeMapper.map_question

    def counted_map_question(self, question, top_k=3, embedding_threshold=0.82):
        nonlocal calls
        calls += 1
        return original_map_question(self, question, top_k, embedding_threshold)

    monkeypatch.setattr(KnowledgeMapper, "map_question", counted_map_question)
    monkeypatch.setattr(knowledge_mapper, "get_knowledge_mapper", lambda: current_mapper[0])

    first = knowledge_mapper.map_question_to_concepts("same question", top_k=3)
    current_mapper[0] = mapper_b
    second = knowledge_mapper.map_question_to_concepts("same question", top_k=3)

    assert first == second == []
    assert calls == 1
    assert knowledge_mapper.map_question_cache_info().hits == 1


def test_concept_map_cache_invalidates_when_embedding_policy_changes(monkeypatch):
    monkeypatch.setattr(knowledge_mapper.config, "QUERY_CACHE_ENABLED", True)
    graph = _minimal_graph(embeddings={"unit": np.array([1.0, 0.0])})
    mapper = KnowledgeMapper(graph=graph)
    mapper._embed_text = lambda text: np.array([1.0, 0.0])
    calls = 0
    original_map_question = KnowledgeMapper.map_question

    def counted_map_question(self, question, top_k=3, embedding_threshold=0.82):
        nonlocal calls
        calls += 1
        return original_map_question(self, question, top_k, embedding_threshold)

    monkeypatch.setattr(KnowledgeMapper, "map_question", counted_map_question)
    monkeypatch.setattr(knowledge_mapper, "get_knowledge_mapper", lambda: mapper)

    monkeypatch.setattr(knowledge_mapper.config, "CONCEPT_MAP_EMBEDDING_MODE", "disabled")
    assert knowledge_mapper.map_question_to_concepts("unmatched", top_k=1) == []

    monkeypatch.setattr(knowledge_mapper.config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first")
    matches = knowledge_mapper.map_question_to_concepts("unmatched", top_k=1)

    assert [(match.concept_id, match.method) for match in matches] == [("unit", "embedding")]
    assert calls == 2


def test_unknown_mapper_cache_owns_identity_until_clear(monkeypatch):
    monkeypatch.setattr(knowledge_mapper.config, "QUERY_CACHE_ENABLED", True)

    class FakeMapper:
        def __init__(self, concept_id):
            self.concept_id = concept_id
            self.calls = 0

        def map_question(self, question, top_k):
            self.calls += 1
            return [
                MatchedConcept(
                    concept_id=self.concept_id,
                    display_name=self.concept_id,
                    chapter="unit",
                    method="exact_alias",
                    score=1.0,
                )
            ]

    first = FakeMapper("first")
    first_ref = weakref.ref(first)
    first_object_id = id(first)
    current_mapper = [first]
    monkeypatch.setattr(knowledge_mapper, "get_knowledge_mapper", lambda: current_mapper[0])

    first_result = knowledge_mapper.map_question_to_concepts("question", top_k=1)
    current_mapper[0] = None
    del first
    gc.collect()

    assert first_ref() is not None
    second = FakeMapper("second")
    assert id(second) != first_object_id
    current_mapper[0] = second
    second_result = knowledge_mapper.map_question_to_concepts("question", top_k=1)

    assert [match.concept_id for match in first_result] == ["first"]
    assert [match.concept_id for match in second_result] == ["second"]
    assert second.calls == 1

    knowledge_mapper.clear_map_question_cache()
    gc.collect()
    assert first_ref() is None


def test_concept_map_cache_is_bounded_and_clear_resets_observability(monkeypatch):
    monkeypatch.setattr(knowledge_mapper.config, "QUERY_CACHE_ENABLED", True)

    class FakeMapper:
        def map_question(self, question, top_k):
            return []

    mapper = FakeMapper()
    monkeypatch.setattr(knowledge_mapper, "get_knowledge_mapper", lambda: mapper)
    maxsize = knowledge_mapper.map_question_cache_info().maxsize

    for index in range(maxsize + 3 if maxsize else 3):
        knowledge_mapper.map_question_to_concepts(f"question-{index}", top_k=1)

    info = knowledge_mapper.map_question_cache_info()
    assert info.currsize <= info.maxsize

    knowledge_mapper.clear_map_question_cache()
    cleared = knowledge_mapper.map_question_cache_info()
    assert cleared.currsize == 0
    assert cleared.hits == 0
    assert cleared.misses == 0


def test_query_normalize_cache_is_observable(monkeypatch):
    utils.clear_query_text_cache()
    monkeypatch.setattr(utils.config, "QUERY_CACHE_ENABLED", True)

    assert utils.normalize_query_text(" SVM 是什么？ ") == "svm是什么？"
    assert utils.normalize_query_text(" SVM 是什么？ ") == "svm是什么？"
    assert utils.query_text_cache_info().hits >= 1


def test_embedding_query_cache_uses_model_base_and_text(monkeypatch):
    embeddings.clear_embedding_query_cache()
    embeddings.reset_embedding_circuit_breaker()
    monkeypatch.setattr(embeddings.config, "EMBEDDING_QUERY_CACHE_SIZE", 8)
    monkeypatch.setattr(embeddings.config, "MODEL_EMBEDDING", "test-embed")
    monkeypatch.setattr(embeddings.config, "BASE_URL", "https://example.test/v1")

    class FakeEmbeddingModel:
        def __init__(self):
            self.calls = 0

        def embed_query(self, text):
            self.calls += 1
            return [1.0, 2.0, 3.0]

    model = FakeEmbeddingModel()

    first = embeddings.embed_query_cached(model, "SVM是什么？")
    second = embeddings.embed_query_cached(model, "SVM是什么？")

    assert first == [1.0, 2.0, 3.0]
    assert second == [1.0, 2.0, 3.0]
    assert first is not second
    assert model.calls == 1
    assert embeddings.embedding_query_cache_info().hits >= 1


def test_embedding_circuit_breaker_fast_fails_after_consecutive_errors(monkeypatch):
    embeddings.clear_embedding_query_cache()
    embeddings.reset_embedding_circuit_breaker()
    monkeypatch.setattr(embeddings.config, "EMBEDDING_QUERY_CACHE_SIZE", 0)
    monkeypatch.setattr(embeddings.config, "EMBEDDING_CIRCUIT_BREAKER_SECONDS", 30)

    class FailingEmbeddingModel:
        def __init__(self):
            self.calls = 0

        def embed_query(self, text):
            self.calls += 1
            raise RuntimeError("network down")

    model = FailingEmbeddingModel()

    for index in range(3):
        with pytest.raises(RuntimeError, match="network down"):
            embeddings.embed_query_cached(model, f"失败请求{index}")

    try:
        embeddings.embed_query_cached(model, "第二次")
    except embeddings.EmbeddingUnavailable:
        pass
    else:
        raise AssertionError("second call should fast-fail via circuit breaker")

    assert model.calls == 3
    embeddings.reset_embedding_circuit_breaker()


def test_embedding_query_timeout_is_bounded_without_opening_circuit_for_one_request(monkeypatch):
    embeddings.clear_embedding_query_cache()
    embeddings.reset_embedding_circuit_breaker()
    monkeypatch.setattr(embeddings.config, "EMBEDDING_QUERY_CACHE_SIZE", 0)
    monkeypatch.setattr(embeddings.config, "EMBEDDING_CIRCUIT_BREAKER_SECONDS", 30)

    class SlowEmbeddingModel:
        def __init__(self):
            self.calls = 0

        def embed_query(self, text):
            self.calls += 1
            time.sleep(0.05)
            return [1.0]

    model = SlowEmbeddingModel()

    token = begin_query_trace({"entrypoint": "unit_test"})
    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed_query_cached(model, "慢查询", timeout_seconds=0.001)
    trace = end_query_trace(token)

    assert model.calls == 2
    assert any(event["stage"] == "embedding.timeout" and event["status"] == "error" for event in trace["events"])
    assert any(event["stage"] == "embedding.retry" for event in trace["events"])
    assert not any(event["stage"] == "embedding.circuit_open" for event in trace["events"])

    assert embeddings.embed_query_cached(model, "第二次", timeout_seconds=0.5) == [1.0]
    assert model.calls == 3
    embeddings.reset_embedding_circuit_breaker()


def test_observe_only_embedding_failure_does_not_open_circuit(monkeypatch):
    embeddings.clear_embedding_query_cache()
    embeddings.reset_embedding_circuit_breaker()
    monkeypatch.setattr(embeddings.config, "EMBEDDING_QUERY_CACHE_SIZE", 0)
    monkeypatch.setattr(embeddings.config, "EMBEDDING_CIRCUIT_BREAKER_SECONDS", 30)

    class FailingEmbeddingModel:
        def embed_query(self, text):
            raise RuntimeError("optional request failed")

    class HealthyEmbeddingModel:
        def __init__(self):
            self.calls = 0

        def embed_query(self, text):
            self.calls += 1
            return [1.0]

    with pytest.raises(RuntimeError, match="optional request failed"):
        embeddings.embed_query_cached(
            FailingEmbeddingModel(),
            "概念映射",
            circuit_mode=embeddings.EmbeddingCircuitMode.OBSERVE_ONLY,
        )

    retrieval_model = HealthyEmbeddingModel()
    assert embeddings.embed_query_cached(retrieval_model, "课程检索") == [1.0]
    assert retrieval_model.calls == 1
    embeddings.reset_embedding_circuit_breaker()
