from ds_course_agent.rag import knowledge_mapper
from ds_course_agent.rag.knowledge_mapper import MatchedConcept
from ds_course_agent.rag.query_pipeline import utils


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
