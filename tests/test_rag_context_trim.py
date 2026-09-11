"""Invariants for exact, token-bounded production retrieval context."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import chromadb
import pytest
from langchain_core.documents import Document

import ds_course_agent.retrieval.service as rag_module
from ds_course_agent.retrieval.context_assembler import (
    ChunkProvenance,
    ContextAssemblyConfig,
    ContextBudgetError,
    ContextProvenanceError,
    RankedContextCandidate,
    assemble_context,
    load_token_counter,
    subtract_interval,
)
from ds_course_agent.retrieval.service import RAGService, clear_rag_retrieval_cache
from ds_course_agent.retrieval.term_resolution import CourseTermIndex, CourseTermMatchKind
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.tools.course_rag import build_sources_from_documents


class CharacterTokenCounter:
    """Deterministic test counter that makes header accounting observable."""

    policy_version = "cl100k_base_v1"

    def count(self, text: str) -> int:
        return len(text)


class RecordingPromptTemplate:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def format(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return f"CTX={kwargs['context']}\nQ={kwargs['input']}"


class FakeChatModel:
    def __init__(self, answer: str = "mock-answer") -> None:
        self.answer = answer
        self.invoked_prompts: list[str] = []
        self.streamed_prompts: list[str] = []

    def invoke(self, prompt: str):
        self.invoked_prompts.append(prompt)
        return MagicMock(content=self.answer)

    def stream(self, prompt: str):
        self.streamed_prompts.append(prompt)
        yield MagicMock(content=self.answer)


@pytest.fixture(autouse=True)
def _clear_retrieval_cache_between_tests():
    clear_rag_retrieval_cache()
    yield
    clear_rag_retrieval_cache()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document(
    *,
    source_id: str = "book",
    source_page: int = 20,
    book_page: int = 12,
    source_text: str = "abcdefghij",
    start: int = 0,
    end: int | None = None,
    chapter: str = "第一章",
) -> Document:
    end = len(source_text) if end is None else end
    content = source_text[start:end]
    return Document(
        page_content=content,
        metadata={
            "metadata_schema_version": "retrieval-provenance/1.0",
            "source": "book.pdf",
            "source_id": source_id,
            "source_page": source_page,
            "book_page": book_page,
            "source_char_start": start,
            "source_char_end": end,
            "content_sha256": _sha256(content),
            "source_page_sha256": _sha256(source_text),
            "source_page_text": source_text,
            "chapter": chapter,
        },
    )


def _candidate(rank: int, **document_kwargs) -> RankedContextCandidate:
    document = _document(**document_kwargs)
    return RankedContextCandidate(
        document=document,
        retrieval_rank=rank,
        distance=rank / 100,
        provenance=ChunkProvenance.from_document(document),
    )


def _assemble(candidates, *, budget: int = 10_000):
    return assemble_context(
        candidates,
        config=ContextAssemblyConfig(token_budget=budget, candidate_depth=10),
        token_counter=CharacterTokenCounter(),
    )


@pytest.mark.parametrize(
    ("interval", "covered", "expected"),
    [
        ((0, 10), [(0, 10)], []),
        ((0, 10), [(0, 4)], [(4, 10)]),
        ((0, 10), [(2, 8)], [(0, 2), (8, 10)]),
        ((2, 8), [(0, 10)], []),
    ],
)
def test_subtract_interval_covers_complete_partial_middle_and_nested_overlap(interval, covered, expected):
    assert subtract_interval(interval, covered) == expected


def test_disjoint_remainder_fragments_preserve_source_order():
    result = _assemble(
        [
            _candidate(1, start=3, end=7),
            _candidate(2, start=0, end=10),
        ]
    )

    second = result.selected[1]
    assert [fragment.text for fragment in second.fragments] == ["abc", "hij"]
    assert [(fragment.interval.char_start, fragment.interval.char_end) for fragment in second.fragments] == [
        (0, 3),
        (7, 10),
    ]
    assert "abc\n[...]\nhij" in result.formatted_context


def test_deduplication_never_crosses_sources_or_pages():
    result = _assemble(
        [
            _candidate(1, source_id="book-a", source_page=20, book_page=12, start=0, end=5),
            _candidate(2, source_id="book-a", source_page=21, book_page=13, start=0, end=5),
            _candidate(3, source_id="book-b", source_page=20, book_page=12, start=0, end=5),
        ]
    )

    assert [item.retrieval_rank for item in result.selected] == [1, 2, 3]
    assert result.duplicate_characters_removed == 0


def test_missing_or_invalid_exact_provenance_fails_clearly():
    with pytest.raises(ContextProvenanceError, match="missing exact production provenance"):
        ChunkProvenance.from_document(Document(page_content="text", metadata={"book_page": 1}))

    document = _document(start=0, end=5)
    document.metadata["source_char_end"] = 6
    with pytest.raises(ContextProvenanceError, match="does not reproduce"):
        ChunkProvenance.from_document(document)


def _write_index_manifest(tmp_path: Path, *, embedding_model: str = "Qwen/Qwen3-Embedding-8B") -> Path:
    persist = tmp_path / "chroma"
    persist.mkdir()
    relative_persist = persist.relative_to(rag_module.PROJECT_ROOT).as_posix()
    digest = "a" * 64
    manifest = {
        "schema_version": "retrieval-production-index/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_bundle": {"path": "candidate.json", "sha256": digest},
        "candidate_index_manifest": {"path": "index.json", "sha256": digest},
        "source_collection": "source",
        "destination_collection": "course_test",
        "persist_directory": relative_persist,
        "document_count": 313,
        "vector_dimension": 4096,
        "embedding_model": embedding_model,
        "embedding_distance": "cosine",
        "embedding_query_prefix": "",
        "metadata_schema_version": "retrieval-provenance/1.0",
        "collection_revision": digest,
        "document_set_sha256": digest,
        "source_vectors_sha256": digest,
        "destination_vectors_sha256": digest,
        "maximum_vector_absolute_error": 0.0,
        "minimum_vector_cosine_similarity": 1.0,
        "code_revision": "test",
        "build_seconds": 1.0,
    }
    path = tmp_path / "production_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_index_manifest_identity_is_required_and_embedding_bound(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(rag_module.config, "RAG_INDEX_MANIFEST_PATH", str(missing), raising=False)
    with pytest.raises(RuntimeError, match="manifest is missing"):
        rag_module._load_index_manifest()

    manifest_path = _write_index_manifest(tmp_path)
    monkeypatch.setattr(rag_module.config, "RAG_INDEX_MANIFEST_PATH", str(manifest_path), raising=False)
    monkeypatch.setattr(rag_module.config, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"), raising=False)
    monkeypatch.setattr(rag_module.config, "collection_name", "course_test", raising=False)
    monkeypatch.setattr(rag_module.config, "MODEL_EMBEDDING", "Qwen/Qwen3-Embedding-8B", raising=False)
    assert rag_module._load_index_manifest().vector_dimension == 4096

    monkeypatch.setattr(rag_module.config, "MODEL_EMBEDDING", "wrong-model", raising=False)
    with pytest.raises(RuntimeError, match="embedding model does not match"):
        rag_module._load_index_manifest()


def test_vector_rank_order_is_required_and_preserved():
    candidates = [_candidate(2), _candidate(1, source_page=21, book_page=13)]
    with pytest.raises(ValueError, match="ascending vector ranks"):
        _assemble(candidates)

    result = _assemble(list(reversed(candidates)))
    assert [item.retrieval_rank for item in result.selected] == [1, 2]


def test_headers_are_included_in_token_accounting_and_budget_is_never_exceeded():
    candidate = _candidate(1, source_text="abc", end=3)
    full = _assemble([candidate])
    header_tokens = full.used_tokens - len("abc")
    assert header_tokens > 0

    constrained = _assemble([candidate], budget=full.used_tokens - 1)
    assert constrained.used_tokens == 0
    assert constrained.stopped_on_overflow is True
    assert constrained.overflow_retrieval_rank == 1


def test_fully_covered_chunk_is_skipped_and_later_candidate_is_considered():
    result = _assemble(
        [
            _candidate(1, start=0, end=5),
            _candidate(2, start=0, end=5),
            _candidate(3, source_page=21, book_page=13, start=0, end=5),
        ]
    )

    assert [item.retrieval_rank for item in result.selected] == [1, 3]
    assert result.skipped_fully_covered_count == 1
    assert result.duplicate_characters_removed == 5


def test_overflow_stops_lower_ranked_candidates_under_frozen_policy():
    first = _candidate(1, source_text="a", end=1)
    second = _candidate(2, source_page=21, book_page=13, source_text="b" * 100, end=100)
    third = _candidate(3, source_page=22, book_page=14, source_text="c", end=1)
    first_only = _assemble([first])

    result = _assemble([first, second, third], budget=first_only.used_tokens + 1)

    assert [item.retrieval_rank for item in result.selected] == [1]
    assert result.stopped_on_overflow is True
    assert result.overflow_retrieval_rank == 2
    assert "c" not in result.formatted_context


def test_selected_documents_match_fragments_actually_sent_to_the_model():
    result = _assemble(
        [
            _candidate(1, start=0, end=6, chapter="第1章"),
            _candidate(2, start=4, end=10, chapter="第1章"),
        ]
    )

    documents = result.documents
    assert [document.page_content for document in documents] == ["abcdef", "ghij"]
    assert [document.metadata["retrieval_rank"] for document in documents] == [1, 2]
    sources = build_sources_from_documents(documents)
    assert len(sources) == 1
    assert sources[0]["reference"].endswith("第12页")


def _service_with_vector_results(monkeypatch, documents: list[Document]) -> RAGService:
    monkeypatch.setattr(rag_module, "embed_query_cached", lambda *args, **kwargs: [1.0, 0.0])
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 10_000, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_TTL_SECONDS", 600.0, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_RETRIEVAL_CACHE_SIZE", 128, raising=False)
    monkeypatch.setattr(rag_module.config, "CHAT_SYSTEM_SUFFIX", "", raising=False)
    service = RAGService.__new__(RAGService)
    service.embedding = object()
    service._token_counter = CharacterTokenCounter()
    service.vector_store_service = MagicMock()
    service.vector_store_service.query.return_value = {
        "ids": [[f"chunk-{index}" for index in range(len(documents))]],
        "documents": [[document.page_content for document in documents]],
        "metadatas": [[document.metadata for document in documents]],
        "distances": [[index / 100 for index in range(len(documents))]],
    }
    service.course_term_index = CourseTermIndex(documents)
    return service


def test_retrieve_returns_only_documents_in_assembled_context(monkeypatch):
    documents = [
        _document(start=0, end=6),
        _document(start=4, end=10),
        _document(source_page=21, book_page=13, source_text="later", end=5),
    ]
    service = _service_with_vector_results(monkeypatch, documents)

    result = service.retrieve("测试问题", top_k=3)

    assert result.has_results is True
    assert [document.page_content for document in result.documents] == ["abcdef", "ghij", "later"]
    assert service.vector_store_service.query.call_args.kwargs["n_results"] == 3
    assert "教材第12页" in result.formatted_context
    assert result.assembly.used_tokens <= result.assembly.token_budget
    assert result.retrieval_query == "测试问题"
    assert result.term_resolution is None


def test_term_typo_uses_only_direct_course_evidence(monkeypatch):
    dikw_page_16 = _document(source_text="DIKW 金字塔模型", end=len("DIKW 金字塔模型"), book_page=16)
    dikw_page_23 = _document(
        source_page=31,
        source_text="DIKW 表示从数据到智慧的转化",
        end=len("DIKW 表示从数据到智慧的转化"),
        book_page=23,
    )
    service = _service_with_vector_results(monkeypatch, [_document(source_text="不相关片段")])
    service.course_term_index = CourseTermIndex([dikw_page_16, dikw_page_23])
    monkeypatch.setattr(
        rag_module,
        "embed_query_cached",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("term lookup must not embed")),
    )

    result = service.retrieve("DMKI是什么？")

    assert result.has_results is True
    assert result.retrieval_query == "DIKW是什么？"
    assert result.term_resolution is not None
    assert result.term_resolution.match_kind is CourseTermMatchKind.CORRECTED
    assert [document.metadata["book_page"] for document in result.documents] == [16, 23]
    service.vector_store_service.query.assert_not_called()


def test_unknown_term_returns_empty_without_vector_neighbors(monkeypatch):
    service = _service_with_vector_results(monkeypatch, [_document(source_text="不相关片段")])
    service.course_term_index = CourseTermIndex(
        [
            _document(source_text="DIKW 金字塔模型", end=len("DIKW 金字塔模型"), book_page=16),
            _document(
                source_page=31,
                source_text="DIKW 表示从数据到智慧的转化",
                end=len("DIKW 表示从数据到智慧的转化"),
                book_page=23,
            ),
        ]
    )
    monkeypatch.setattr(
        rag_module,
        "embed_query_cached",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unknown term must not embed")),
    )

    result = service.retrieve("ZZZZ是什么？")

    assert result.has_results is False
    assert result.documents == []
    assert result.term_resolution is not None
    assert result.term_resolution.match_kind is CourseTermMatchKind.UNRESOLVED
    service.vector_store_service.query.assert_not_called()


def test_term_resolution_uses_current_query_instead_of_enriched_history(monkeypatch):
    dikw_documents = [
        _document(source_text="DIKW 金字塔模型", end=len("DIKW 金字塔模型"), book_page=16),
        _document(
            source_page=31,
            source_text="DIKW 表示从数据到智慧的转化",
            end=len("DIKW 表示从数据到智慧的转化"),
            book_page=23,
        ),
    ]
    service = _service_with_vector_results(monkeypatch, [_document(source_text="不相关附录")])
    service.course_term_index = CourseTermIndex(dikw_documents)
    enriched_query = (
        "最近对话上下文：\n用户: BCA是什么？\n助手: 请补充具体问题。\n\n"
        "请结合上下文理解学生当前追问，再检索课程资料回答。\n当前问题：DWKI是什么？"
    )
    monkeypatch.setattr(
        rag_module,
        "embed_query_cached",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("corrected term must not embed")),
    )

    result = service.retrieve(enriched_query, term_resolution_query="DWKI是什么？")

    assert result.retrieval_query == "DIKW是什么？"
    assert result.term_resolution is not None
    assert result.term_resolution.match_kind is CourseTermMatchKind.CORRECTED
    assert [document.metadata["book_page"] for document in result.documents] == [16, 23]
    service.vector_store_service.query.assert_not_called()


def test_retrieve_cache_hit_returns_document_clones(monkeypatch):
    service = _service_with_vector_results(monkeypatch, [_document(source_text="PCA", end=3)])

    first = service.retrieve("PCA 有什么作用？", top_k=1)
    second = service.retrieve(" PCA 有什么作用？ ", top_k=1)

    assert first.formatted_context == second.formatted_context
    assert first.documents[0].metadata == second.documents[0].metadata
    assert first.documents[0] is not second.documents[0]
    assert service.vector_store_service.query.call_count == 0


def test_retrieval_cache_key_changes_with_policy_index_and_model(monkeypatch):
    def key() -> str:
        return rag_module._retrieval_cache_key(
            "question",
            candidate_depth=10,
            similarity_threshold=1.0,
            revision="revision-a",
        )

    original = key()
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 2048, raising=False)
    assert key() != original
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 4096, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_DEDUPLICATION_MODE", "policy-v2", raising=False)
    assert key() != original
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_DEDUPLICATION_MODE", "exact_source_interval_v1", raising=False)
    monkeypatch.setattr(rag_module.config, "collection_name", "new-index", raising=False)
    assert key() != original
    monkeypatch.setattr(rag_module.config, "collection_name", "rag_knowledge_base", raising=False)
    monkeypatch.setattr(rag_module.config, "MODEL_EMBEDDING", "embedding-v2", raising=False)
    assert key() != original


def test_complete_answer_prompt_budget_is_validated(monkeypatch):
    service = RAGService.__new__(RAGService)
    service._token_counter = CharacterTokenCounter()
    service.prompt_template = RecordingPromptTemplate()
    service.chat_model = FakeChatModel()
    monkeypatch.setattr(rag_module.config, "CHAT_SYSTEM_SUFFIX", "", raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 100, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 10, raising=False)
    monkeypatch.setattr(rag_module.config, "CONTEXT_WINDOW_TOKENS", 25, raising=False)

    with pytest.raises(ContextBudgetError, match="complete RAG prompt"):
        service.answer_with_context("question", "context")
    assert service.chat_model.invoked_prompts == []


def test_answer_prompt_trace_reports_token_contract(monkeypatch):
    service = RAGService.__new__(RAGService)
    service._token_counter = CharacterTokenCounter()
    service.prompt_template = RecordingPromptTemplate()
    service.chat_model = FakeChatModel()
    monkeypatch.setattr(rag_module.config, "CHAT_SYSTEM_SUFFIX", "", raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 100, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 10, raising=False)
    monkeypatch.setattr(rag_module.config, "CONTEXT_WINDOW_TOKENS", 100, raising=False)

    token = begin_query_trace({"entrypoint": "unit_test"})
    answer = service.answer_with_context("question", "context")
    trace = end_query_trace(token)

    assert answer.answer == "mock-answer"
    event = next(event for event in trace["events"] if event["stage"] == "rag.answer.prompt")
    assert event["data"]["context_tokens"] == len("context")
    assert event["data"]["answer_reserved_tokens"] == 10
    assert event["data"]["context_window_tokens"] == 100


def test_stream_answer_uses_the_same_prompt_budget_validation(monkeypatch):
    service = RAGService.__new__(RAGService)
    service._token_counter = CharacterTokenCounter()
    service.prompt_template = RecordingPromptTemplate()
    service.chat_model = FakeChatModel()
    monkeypatch.setattr(rag_module.config, "CHAT_SYSTEM_SUFFIX", "", raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 100, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 10, raising=False)
    monkeypatch.setattr(rag_module.config, "CONTEXT_WINDOW_TOKENS", 100, raising=False)

    assert list(service.stream_answer_with_context("question", "context")) == ["mock-answer"]
    assert service.chat_model.streamed_prompts == ["CTX=context\nQ=question"]


def test_ret_0053_rank_7_evidence_enters_real_4096_token_context(monkeypatch):
    root = Path.cwd()
    retrieval_report_path = root / "var/artifacts/kb_eval/retrieval_strategy_20260910/vector_raw_unseen_test_v2.json"
    promoted_path = root / "var/chroma_candidates/production_switch_20260910/qwen3_8b_native/chroma"
    if not retrieval_report_path.is_file() or not promoted_path.is_dir():
        pytest.skip("frozen ret-0053 ranking and promoted index are local evaluation artifacts")

    report = json.loads(retrieval_report_path.read_text(encoding="utf-8"))
    row = next(query for query in report["queries"] if query["id"] == "ret-0053")
    retrieved = row["retrieved"]
    chunk_ids = [item["chunk_id"] for item in retrieved]
    collection = chromadb.PersistentClient(path=str(promoted_path)).get_collection("course_c37b7b78")
    payload = collection.get(ids=chunk_ids, include=["documents", "metadatas"])
    by_id = {
        chunk_id: Document(page_content=document, metadata=metadata)
        for chunk_id, document, metadata in zip(payload["ids"], payload["documents"], payload["metadatas"], strict=True)
    }
    candidates = [
        RankedContextCandidate(
            document=by_id[item["chunk_id"]],
            retrieval_rank=item["rank"],
            distance=max(0.0, 1.0 - item["ranking_score"]),
            provenance=ChunkProvenance.from_document(by_id[item["chunk_id"]]),
        )
        for item in retrieved
    ]
    counter = load_token_counter(root / "var/cache/tiktoken")
    assembly = assemble_context(
        candidates,
        config=ContextAssemblyConfig(token_budget=4096, candidate_depth=10),
        token_counter=counter,
    )

    selected_pages = {fragment.interval.source_page for item in assembly.selected for fragment in item.fragments}
    assert len(assembly.selected) == 10
    assert [item.retrieval_rank for item in assembly.selected] == list(range(1, 11))
    assert 114 in selected_pages
    assert 119 in selected_pages
    assert assembly.selected[6].retrieval_rank == 7
    assert assembly.used_tokens == 2760

    service = RAGService.__new__(RAGService)
    service._token_counter = counter
    service.prompt_template = rag_module.build_rag_prompt_template()
    monkeypatch.setattr(rag_module.config, "RAG_CONTEXT_MAX_TOKENS", 4096, raising=False)
    monkeypatch.setattr(rag_module.config, "RAG_ANSWER_MAX_TOKENS", 768, raising=False)
    monkeypatch.setattr(rag_module.config, "CONTEXT_WINDOW_TOKENS", 8192, raising=False)
    prompt = service._prepare_answer_prompt(row["query"], assembly.formatted_context, mode="validation")
    assert counter.count(prompt) + 768 <= 8192
