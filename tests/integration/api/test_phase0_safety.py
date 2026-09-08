import json
import threading

from ds_course_agent.teaching.memory_core import MemoryCore


def test_state_save_lock_is_real_lock():
    from ds_course_agent.api import state

    lock_type = type(threading.Lock())
    assert isinstance(state._save_lock, lock_type)


def test_concurrent_state_save_writes_valid_json(monkeypatch, tmp_path):
    from ds_course_agent.api import state

    state_file = tmp_path / "backend_state.json"
    monkeypatch.setattr(state, "STATE_FILE", state_file)
    state._sessions.clear()
    state._chat_history.clear()
    state._deleted_session_ids.clear()

    def worker(index: int) -> None:
        with state.state_lock():
            session_id = f"session-{index}"
            state._sessions[session_id] = {
                "title": f"会话 {index}",
                "student_id": "student",
                "created_at": "2026-07-17T00:00:00",
                "updated_at": "2026-07-17T00:00:00",
                "message_count": 1,
            }
            state._chat_history[session_id] = [{"role": "user", "content": str(index)}]
        state._save()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(payload["sessions"]) == 25
    assert len(payload["chat_history"]) == 25


def test_memory_core_default_uses_config_chat_history_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("ds_course_agent.teaching.memory_core.config.CHAT_HISTORY_DIR", str(tmp_path))

    memory = MemoryCore()

    assert memory.base_dir == tmp_path


def test_hybrid_retriever_does_not_mutate_shared_doc_metadata():
    from langchain_core.documents import Document

    from ds_course_agent.retrieval.hybrid_retriever import HybridRetriever
    from ds_course_agent.shared import embeddings

    embeddings.reset_embedding_circuit_breaker()
    embeddings.clear_embedding_query_cache()

    retriever = HybridRetriever.__new__(HybridRetriever)
    import threading

    from ds_course_agent.shared.kb_revision import read_kb_revision

    retriever.collection_name = "test"
    retriever._revision = read_kb_revision("test")
    retriever._corpus_lock = threading.RLock()
    retriever.k = 1
    retriever.use_rerank = False
    retriever.reranker = None
    retriever.collection = object()
    retriever.documents = [Document(page_content="SVM 核函数", metadata={"chunk_id": "svm"})]
    retriever.bm25_retriever = type(
        "FakeBM25",
        (),
        {"retrieve": lambda self, query, top_k: [(0, 1.0)]},
    )()
    retriever._doc_text_to_index = {"SVM 核函数": 0}
    retriever._doc_prefix_to_index = {"SVM 核函数": 0}
    retriever._vector_search = lambda query, top_k, snapshot: []

    docs = retriever.retrieve("SVM", top_k=1)

    assert docs[0] is not retriever.documents[0]
    assert docs[0].metadata["fused_score"] > 0
    assert "fused_score" not in retriever.documents[0].metadata
