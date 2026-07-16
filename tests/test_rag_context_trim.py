from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

import ds_course_agent.rag.rag as rag_module
from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.rag.rag import RAGService, clear_rag_retrieval_cache
from ds_course_agent.tools.course_rag import build_sources_from_documents


@pytest.fixture(autouse=True)
def _clear_retrieval_cache_between_tests():
    clear_rag_retrieval_cache()
    yield
    clear_rag_retrieval_cache()


class RecordingPromptTemplate:
    def __init__(self):
        self.calls = []

    def format(self, **kwargs):
        self.calls.append(kwargs)
        return f"CTX={kwargs['context']}\nQ={kwargs['input']}"


class FakeChatModel:
    def __init__(self, answer="mock-answer"):
        self.answer = answer
        self.invoked_prompts = []
        self.streamed_prompts = []

    def invoke(self, prompt):
        self.invoked_prompts.append(prompt)
        return MagicMock(content=self.answer)

    def stream(self, prompt):
        self.streamed_prompts.append(prompt)
        yield MagicMock(content=self.answer)


def _set_trim_config(monkeypatch, *, enabled=True, max_chars=120, doc_max_chars=40):
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_TRIM_ENABLED", enabled, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_CHARS", max_chars, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_DOC_MAX_CHARS", doc_max_chars, raising=False)
    monkeypatch.setattr(rag_module.config, "CHAT_SYSTEM_SUFFIX", "", raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_TTL_SECONDS", 600.0, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_SIZE", 128, raising=False)


def _make_doc(source, page, content, extra_metadata=None):
    metadata = {"source": source, "book_page": page}
    if extra_metadata:
        metadata.update(extra_metadata)
    return Document(page_content=content, metadata=metadata)


def test_retrieve_trims_each_document_and_total_budget_preserves_metadata(monkeypatch):
    _set_trim_config(monkeypatch, enabled=True, max_chars=300, doc_max_chars=35)

    service = RAGService.__new__(RAGService)
    service.use_hybrid = True
    service.hybrid_retriever = MagicMock()
    service.hybrid_retriever.retrieve.return_value = [
        _make_doc("chapter-1.pdf", 12, "甲" * 80, {"chapter": "第一章"}),
        _make_doc("chapter-2.pdf", 18, "乙" * 80, {"chapter": "第二章"}),
        _make_doc("chapter-3.pdf", 25, "丙" * 80, {"chapter": "第三章"}),
    ]

    token = begin_query_trace({"entrypoint": "unit_test"})
    result = service.retrieve("测试问题", top_k=3)
    trace = end_query_trace(token)

    assert result.has_results is True
    assert len(result.documents) == 3
    assert len(result.formatted_context) <= 300
    assert result.formatted_context.count("文档片段：") == 2
    assert "chapter-1.pdf" in result.formatted_context
    assert "chapter-2.pdf" in result.formatted_context
    assert "chapter-3.pdf" not in result.formatted_context
    assert "page_note" in result.formatted_context
    assert "甲" * 80 not in result.formatted_context
    assert build_sources_from_documents(result.documents)[0] == {"reference": "《第一章》第12页"}
    assert any(
        marker in result.formatted_context
        for marker in ("[片段已裁剪", "[片段已按总上下文预算裁剪", "[片段因上下文预算省略]")
    )
    assert any(
        event["stage"] == "rag.context_trim"
        and event["data"]["location"] == "rag.format_documents"
        for event in trace["events"]
    )


def test_retrieve_cache_hit_avoids_second_retriever_call_and_returns_clones(monkeypatch):
    _set_trim_config(monkeypatch, enabled=True, max_chars=300, doc_max_chars=35)

    service = RAGService.__new__(RAGService)
    service.use_hybrid = True
    service.hybrid_retriever = MagicMock()
    service.hybrid_retriever.retrieve.return_value = [
        _make_doc("chapter-cache.pdf", 22, "PCA 可以用于降维", {"chapter": "第7章"})
    ]

    token = begin_query_trace({"entrypoint": "unit_test"})
    first = service.retrieve("PCA 有什么作用？", top_k=1)
    second = service.retrieve(" PCA 有什么作用？ ", top_k=1)
    trace = end_query_trace(token)

    assert first.formatted_context == second.formatted_context
    assert first.documents[0].metadata == second.documents[0].metadata
    assert first.documents[0] is not second.documents[0]
    assert service.hybrid_retriever.retrieve.call_count == 1
    assert any(event["stage"] == "rag.retrieve.cache_miss" for event in trace["events"])
    assert any(event["stage"] == "rag.retrieve.cache_store" for event in trace["events"])
    assert any(event["stage"] == "rag.retrieve.cache_hit" for event in trace["events"])


def test_retrieve_cache_key_includes_top_k(monkeypatch):
    _set_trim_config(monkeypatch, enabled=True, max_chars=500, doc_max_chars=80)

    service = RAGService.__new__(RAGService)
    service.use_hybrid = True
    service.hybrid_retriever = MagicMock()
    service.hybrid_retriever.retrieve.side_effect = [
        [_make_doc("top1.pdf", 1, "top one")],
        [
            _make_doc("top1.pdf", 1, "top one"),
            _make_doc("top2.pdf", 2, "top two"),
        ],
    ]

    first = service.retrieve("PCA 有什么作用？", top_k=1)
    second = service.retrieve("PCA 有什么作用？", top_k=2)

    assert len(first.documents) == 1
    assert len(second.documents) == 2
    assert service.hybrid_retriever.retrieve.call_count == 2


def test_format_documents_keeps_full_content_when_trim_disabled(monkeypatch):
    _set_trim_config(monkeypatch, enabled=False, max_chars=20, doc_max_chars=5)

    service = RAGService.__new__(RAGService)
    long_text = "课程资料" * 30
    docs = [_make_doc("no-trim.pdf", 7, long_text)]

    formatted_context = service._format_documents(docs)

    assert long_text in formatted_context
    assert len(formatted_context) > 20
    assert "no-trim.pdf" in formatted_context
    assert "page_note" in formatted_context
    assert "片段已裁剪" not in formatted_context
    assert "片段已按总上下文预算裁剪" not in formatted_context
    assert "片段因上下文预算省略" not in formatted_context


def test_answer_with_context_applies_final_context_budget_protection(monkeypatch):
    _set_trim_config(monkeypatch, enabled=True, max_chars=150, doc_max_chars=25)

    service = RAGService.__new__(RAGService)
    prompt_template = RecordingPromptTemplate()
    fake_model = FakeChatModel()
    service.prompt_template = prompt_template
    service.chat_model = fake_model

    context = (
        "文档片段：" + ("数据" * 60) + "\n"
        "文档元数据：{'source': 'final-guard.pdf', 'page': 8, 'page_note': '教材第8页'}"
    )

    token = begin_query_trace({"entrypoint": "unit_test"})
    answer = service.answer_with_context("什么是数据科学？", context)
    trace = end_query_trace(token)

    assert answer.answer == "mock-answer"
    assert fake_model.invoked_prompts
    assert prompt_template.calls, "prompt_template.format should be called"

    passed_context = prompt_template.calls[0]["context"]
    expected_max_tokens = int(getattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 384) or 384)
    assert len(passed_context) <= 150
    assert "final-guard.pdf" in passed_context
    assert "page_note" in passed_context
    assert "[片段已按总上下文预算裁剪" in passed_context or "[片段因上下文预算省略]" in passed_context
    assert any(
        event["stage"] == "rag.answer.prompt_compact"
        and event["data"]["mode"] == "sync"
        and event["data"]["context_chars"] == len(passed_context)
        and event["data"]["max_tokens"] == expected_max_tokens
        for event in trace["events"]
    )


def test_stream_answer_with_context_applies_final_context_budget_protection(monkeypatch):
    _set_trim_config(monkeypatch, enabled=True, max_chars=150, doc_max_chars=25)

    service = RAGService.__new__(RAGService)
    prompt_template = RecordingPromptTemplate()
    fake_model = FakeChatModel()
    service.prompt_template = prompt_template
    service.chat_model = fake_model

    context = (
        "文档片段：" + ("数据" * 60) + "\n"
        "文档元数据：{'source': 'stream-guard.pdf', 'page': 9, 'page_note': '教材第9页'}"
    )

    token = begin_query_trace({"entrypoint": "unit_test"})
    chunks = list(service.stream_answer_with_context("什么是数据科学？", context))
    trace = end_query_trace(token)

    assert chunks == ["mock-answer"]
    assert fake_model.streamed_prompts
    assert prompt_template.calls, "prompt_template.format should be called"

    passed_context = prompt_template.calls[0]["context"]
    expected_max_tokens = int(getattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 384) or 384)
    assert len(passed_context) <= 150
    assert "stream-guard.pdf" in passed_context
    assert "page_note" in passed_context
    assert "[片段已按总上下文预算裁剪" in passed_context or "[片段因上下文预算省略]" in passed_context
    assert any(
        event["stage"] == "rag.answer.prompt_compact"
        and event["data"]["mode"] == "stream"
        and event["data"]["context_chars"] == len(passed_context)
        and event["data"]["max_tokens"] == expected_max_tokens
        for event in trace["events"]
    )
