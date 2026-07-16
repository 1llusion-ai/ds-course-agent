import time

import pytest

from ds_course_agent.rag import knowledge_mapper
from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.rag.knowledge_mapper import MatchedConcept
from ds_course_agent.rag.query_pipeline import utils
from ds_course_agent.shared import embeddings


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


def test_embedding_circuit_breaker_fast_fails_after_error(monkeypatch):
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

    try:
        embeddings.embed_query_cached(model, "第一次")
    except RuntimeError:
        pass
    else:
        raise AssertionError("first failing embedding call should raise")

    try:
        embeddings.embed_query_cached(model, "第二次")
    except embeddings.EmbeddingUnavailable:
        pass
    else:
        raise AssertionError("second call should fast-fail via circuit breaker")

    assert model.calls == 1
    embeddings.reset_embedding_circuit_breaker()


def test_embedding_query_timeout_guard_opens_circuit(monkeypatch):
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

    assert model.calls == 1
    assert any(
        event["stage"] == "embedding.timeout"
        and event["status"] == "error"
        for event in trace["events"]
    )

    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed_query_cached(model, "第二次")
    assert model.calls == 1
    embeddings.reset_embedding_circuit_breaker()
