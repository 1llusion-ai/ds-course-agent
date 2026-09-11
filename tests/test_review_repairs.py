"""Regression tests for independently reproduced architecture-review defects."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ds_course_agent.shared.kb_revision import knowledge_base_write, read_kb_revision


def test_embedding_cache_uses_actual_client_and_settings(monkeypatch):
    from ds_course_agent.shared import embeddings as module

    module.clear_embedding_query_cache()
    module.reset_embedding_circuit_breaker()
    monkeypatch.setattr(module.config, "EMBEDDING_QUERY_CACHE_SIZE", 10)
    a = SimpleNamespace(model="A", embed_query=Mock(return_value=[1.0]))
    b = SimpleNamespace(model="B", embed_query=Mock(return_value=[2.0]))
    assert module.embed_query_cached(a, "q") == [1.0]
    assert module.embed_query_cached(b, "q") == [2.0]
    assert module.embed_query_cached(a, "q") == [1.0]
    a.embed_query.assert_called_once()
    a.model = "C"
    a.embed_query.return_value = [3.0]
    assert module.embed_query_cached(a, "q") == [3.0]
    module.clear_embedding_query_cache()


def test_kb_revision_invalidates_partial_writes(tmp_path):
    directory = str(tmp_path)
    old = read_kb_revision("course", directory)
    with pytest.raises(RuntimeError):
        with knowledge_base_write("course", directory):
            during = read_kb_revision("course", directory)
            assert during != old
            raise RuntimeError("partial write")
    assert read_kb_revision("course", directory) not in {old, during}


def test_recreated_chroma_collection_is_reacquired(tmp_path, monkeypatch):
    import chromadb

    import ds_course_agent.retrieval.hybrid_retriever as hybrid
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(hybrid, "OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(hybrid, "embed_query_cached", lambda *args, **kw: [1.0, 0.0])
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.create_collection("revision-test", embedding_function=None)
    collection.add(ids=["old"], documents=["old corpus"], embeddings=[[1.0, 0.0]], metadatas=[{"source": "old"}])
    retriever = hybrid.HybridRetriever(collection_name="revision-test", use_rerank=False)
    assert retriever.retrieve("corpus")[0].page_content == "old corpus"
    with knowledge_base_write("revision-test"):
        client.delete_collection("revision-test")
        collection = client.create_collection("revision-test", embedding_function=None)
        collection.add(ids=["new"], documents=["new corpus"], embeddings=[[1.0, 0.0]], metadatas=[{"source": "new"}])
    assert retriever.retrieve("corpus")[0].page_content == "new corpus"


def test_live_corpus_replacement_and_clear_refresh_bm25_and_cache(tmp_path, monkeypatch):
    import ds_course_agent.retrieval.service as rag
    import ds_course_agent.shared.config as config
    from ds_course_agent.retrieval.service import RAGService, clear_rag_retrieval_cache

    monkeypatch.setattr(config, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(config, "collection_name", "review")
    monkeypatch.setattr(config, "RAG_RETRIEVAL_CACHE_ENABLED", True)
    documents = ["old corpus"]

    def metadata(text):
        digest = hashlib.sha256(text.encode()).hexdigest()
        return {
            "metadata_schema_version": "retrieval-provenance/1.0",
            "source_id": "review",
            "source_page": 9,
            "book_page": 1,
            "source_char_start": 0,
            "source_char_end": len(text),
            "content_sha256": digest,
            "source_page_sha256": digest,
            "source_page_text": text,
        }

    vector_store = Mock()
    vector_store.query.side_effect = lambda **kw: {
        "ids": [[f"doc-{index}" for index in range(len(documents))]],
        "documents": [list(documents)],
        "metadatas": [[metadata(text) for text in documents]],
        "distances": [[0.1 for _ in documents]],
    }
    monkeypatch.setattr(rag, "embed_query_cached", lambda *args, **kw: [1.0])

    class CharacterTokenCounter:
        policy_version = "cl100k_base_v1"

        def count(self, text):
            return len(text)

    service = RAGService.__new__(RAGService)
    service.embedding = object()
    service.vector_store_service = vector_store
    service._token_counter = CharacterTokenCounter()
    service.course_term_index = Mock()
    service.course_term_index.lookup.return_value = None
    clear_rag_retrieval_cache()
    try:
        assert service.retrieve("corpus").documents[0].page_content == "old corpus"
        assert service.retrieve("corpus").documents[0].page_content == "old corpus"
        assert vector_store.query.call_count == 1
        with knowledge_base_write("review", str(tmp_path)):
            documents[:] = ["new corpus"]
        assert service.retrieve("corpus").documents[0].page_content == "new corpus"
        assert vector_store.query.call_count == 2
        with knowledge_base_write("review", str(tmp_path)):
            documents.clear()
        assert not service.retrieve("corpus").has_results
    finally:
        clear_rag_retrieval_cache()


def test_ingest_publishes_revision_for_failed_batch(tmp_path):
    from ds_course_agent.kb.store import CourseKnowledgeBase

    kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
    kb.collection_name = "review"
    kb._config = SimpleNamespace(CHROMA_PERSIST_DIR=str(tmp_path))
    kb.hashes = {}
    kb._compute_chunk_hash = lambda chunk: "hash"
    kb._build_metadata = lambda chunk: {}
    kb._save_hashes = lambda: None
    kb.vector_store = Mock()
    kb.vector_store.add_texts.side_effect = RuntimeError("partial write")
    result = kb.ingest_chunks([SimpleNamespace(content="x", metadata=SimpleNamespace(chunk_type="semantic"))], "file")
    assert result.error_count == 1
    assert read_kb_revision("review", str(tmp_path)) != "legacy"


def test_ingest_publishes_one_revision_window_for_all_batches(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from ds_course_agent.kb import store

    events = []

    @contextmanager
    def recording_write(collection_name, persist_dir):
        events.append(("enter", collection_name, persist_dir))
        try:
            yield
        finally:
            events.append(("exit", collection_name, persist_dir))

    monkeypatch.setattr(store, "knowledge_base_write", recording_write)
    kb = store.CourseKnowledgeBase.__new__(store.CourseKnowledgeBase)
    kb.collection_name = "review"
    kb._config = SimpleNamespace(CHROMA_PERSIST_DIR=str(tmp_path))
    kb.hashes = {}
    kb._compute_chunk_hash = lambda chunk: chunk.content
    kb._build_metadata = lambda chunk: {}
    kb._save_hashes = lambda: None
    kb.vector_store = Mock()
    chunks = [
        SimpleNamespace(content=str(index), metadata=SimpleNamespace(chunk_type="semantic")) for index in range(3)
    ]

    result = kb.ingest_chunks(chunks, "file", batch_size=1)

    assert result.success_count == 3
    assert kb.vector_store.add_texts.call_count == 3
    assert events == [
        ("enter", "review", str(tmp_path)),
        ("exit", "review", str(tmp_path)),
    ]


def test_clear_history_updates_metadata_once(monkeypatch):
    from ds_course_agent.api import chat_sessions as sessions

    monkeypatch.setattr(sessions, "_chat_history", {"s": [{"content": "x"}]})
    monkeypatch.setattr(sessions, "_sessions", {"s": {"message_count": 1}})
    save = Mock()
    monkeypatch.setattr(sessions, "_save_state", save)
    sessions.clear_messages("s")
    assert sessions.message_count("s") == sessions._sessions["s"]["message_count"] == 0
    save.assert_called_once()


def test_clear_history_waits_for_active_session_operation(monkeypatch):
    """Clearing history cannot invalidate an in-flight continuation target."""

    from ds_course_agent.api import chat_application, chat_sessions
    from ds_course_agent.api.schemas.chat import ChatMessage

    session_id = "clear-race-session"
    student_id = "clear-race-student"
    monkeypatch.setattr(chat_sessions, "_chat_history", {})
    monkeypatch.setattr(
        chat_sessions,
        "_sessions",
        {session_id: {"id": session_id, "student_id": student_id, "title": "race"}},
    )
    monkeypatch.setattr(chat_sessions, "_save_state", Mock())
    chat_sessions.append_message_locked(
        session_id,
        ChatMessage(role="assistant", content="partial"),
        save=False,
    )
    operation_lock = chat_sessions.session_operation_lock(session_id)
    operation_lock.acquire()

    async def exercise() -> None:
        clear_task = asyncio.create_task(chat_application.clear_history(session_id, student_id))
        await asyncio.sleep(0.03)
        assert not clear_task.done()
        assert chat_sessions.message_count(session_id) == 1
        operation_lock.release()
        assert await clear_task == {"message": "聊天记录已清空"}

    try:
        asyncio.run(exercise())
        assert chat_sessions.message_count(session_id) == 0
    finally:
        if operation_lock.locked():
            operation_lock.release()


def test_stream_worker_terminalizes_when_continuation_target_disappears(monkeypatch):
    from ds_course_agent.api import chat_sessions, chat_streaming
    from ds_course_agent.api.schemas.chat import ChatMessage
    from ds_course_agent.api.sse import iter_stream_job_events

    session_id = "missing-continuation-target"
    student_id = "student"
    monkeypatch.setattr(chat_sessions, "_chat_history", {session_id: []})
    monkeypatch.setattr(
        chat_sessions,
        "_sessions",
        {session_id: {"id": session_id, "student_id": student_id}},
    )
    operation_lock = chat_sessions.session_operation_lock(session_id)
    operation_lock.acquire()
    missing_target = {"role": "assistant", "content": "gone"}

    job = chat_streaming.launch_stream_worker(
        session_id=session_id,
        student_id=student_id,
        operation_lock=operation_lock,
        event_source=lambda: iter([{"type": "final", "content": "continued", "stream_id": "stream"}]),
        message_timestamp=datetime.now(),
        web_search=False,
        replace_message_item=missing_target,
        base_message=ChatMessage(role="assistant", content="partial", generation_status="stopped"),
    )

    async def collect_events():
        return [event async for event in iter_stream_job_events(job, include_snapshot=False)]

    events = asyncio.run(asyncio.wait_for(collect_events(), timeout=1))

    assert events[-1]["type"] == "final"
    assert events[-1]["error"]
    assert events[-1]["message"]["generation_status"] == "error"
    assert job.snapshot().terminal is True


def test_continuation_accepts_iso_normalization_but_rejects_wrong_turn(monkeypatch):
    from fastapi import HTTPException

    from ds_course_agent.api import chat_sessions as sessions

    local = datetime(2026, 9, 8, 12, 30, 0, 123456)
    normalized = local.astimezone(timezone.utc).replace(microsecond=123000)
    item = {"role": "assistant", "generation_status": "stopped", "timestamp": local.isoformat()}
    monkeypatch.setattr(sessions, "_chat_history", {"s": [item]})
    assert sessions.find_stopped_assistant_turn("s", normalized) is item
    with pytest.raises(HTTPException) as error:
        sessions.find_stopped_assistant_turn("s", normalized + timedelta(seconds=1))
    assert error.value.status_code == 409
    restored = sessions.message_from_dict({"role": "assistant", "content": "x", "timestamp": "bad"})
    assert isinstance(restored.timestamp, datetime)


def test_generator_close_finishes_query_trace(monkeypatch):
    from ds_course_agent.api import core_bridge
    from ds_course_agent.shared import query_trace

    service = SimpleNamespace(stream_chat_with_history=lambda **kw: iter([{"type": "delta", "delta": "x"}]))
    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: service)
    finish = Mock(wraps=query_trace.end_query_trace)
    monkeypatch.setattr(query_trace, "end_query_trace", finish)
    stream = core_bridge.stream_chat_with_history("q", "s", "u")
    next(stream)
    stream.close()
    assert query_trace._query_trace_ctx.get() is None
    assert finish.call_args.kwargs["status"] == "cancelled"


def test_continuation_cancelled_after_initial_progress_finishes_trace():
    from ds_course_agent.api.core_bridge import stream_continue_with_history
    from ds_course_agent.shared import query_trace

    stream = stream_continue_with_history(partial_content="partial", session_id="s", student_id="u")
    assert next(stream)["type"] == "progress"
    stream.close()
    assert query_trace._query_trace_ctx.get() is None


@pytest.mark.parametrize("buffered", [False, True])
def test_turn_preserves_degraded_result_and_sources(monkeypatch, buffered):
    from ds_course_agent.agent import turn_runner
    from ds_course_agent.agent.events import RetrievalEndEvent, RouteResultEvent
    from ds_course_agent.agent.routing import RouteExecutionResult
    from tests.test_turn_events import _History, _state

    state = _state(_History())
    source = {"reference": "chapter"}
    result = RouteExecutionResult(
        content="fallback",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
        sources=[source],
        retrieval_attempted=True,
        used_retrieval=True,
        degraded=True,
    )
    event = (
        RouteResultEvent(result)
        if buffered
        else RetrievalEndEvent(
            stream_id="s",
            sources=(source,),
            retrieval_attempted=True,
            used_retrieval=True,
            message="fallback",
            degraded=True,
        )
    )
    monkeypatch.setattr(turn_runner, "iter_route_response", lambda *args: iter(["fallback", event]))
    agent = SimpleNamespace(_prepare_query_route=lambda *args: state)
    events = list(turn_runner.iter_turn_events(agent, "q", "s", stream=True))
    assert events[-1].result.degraded is True
    assert events[-1].result.sources == [source]
    assert not any(isinstance(item, RouteResultEvent) for item in events)
