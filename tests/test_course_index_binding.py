from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ds_course_agent.retrieval.service as retrieval_module
from ds_course_agent.courses import CourseIndexBinding
from ds_course_agent.retrieval.service import RAGService, build_rag_prompt_template


def _manifest_payload(*, persist_directory: str, collection_name: str, revision: str) -> dict:
    digest = "a" * 64
    return {
        "schema_version": "retrieval-production-index/1.0",
        "created_at": "2026-10-20T00:00:00+00:00",
        "candidate_bundle": {"path": "candidate.json", "sha256": digest},
        "candidate_index_manifest": {"path": "index.json", "sha256": digest},
        "source_collection": "source",
        "destination_collection": collection_name,
        "persist_directory": persist_directory,
        "document_count": 1,
        "vector_dimension": 2,
        "embedding_model": "course-embedding",
        "embedding_distance": "cosine",
        "embedding_query_prefix": "",
        "metadata_schema_version": "retrieval-provenance/1.0",
        "collection_revision": revision,
        "document_set_sha256": digest,
        "source_vectors_sha256": digest,
        "destination_vectors_sha256": digest,
        "maximum_vector_absolute_error": 0.0,
        "minimum_vector_cosine_similarity": 1.0,
        "code_revision": "test",
        "build_seconds": 0.0,
    }


def test_load_manifest_uses_explicit_binding_identity(monkeypatch, tmp_path):
    persist = tmp_path / "course-index"
    persist.mkdir()
    manifest_path = tmp_path / "manifest.json"
    revision = "b" * 64
    manifest_path.write_text(
        json.dumps(
            _manifest_payload(
                persist_directory=str(persist),
                collection_name="course-two",
                revision=revision,
            )
        ),
        encoding="utf-8",
    )
    binding = CourseIndexBinding(
        collection_name="course-two",
        persist_directory=str(persist),
        manifest_path=str(manifest_path),
        revision=revision,
        embedding_model="course-embedding",
    )
    monkeypatch.setattr(retrieval_module.config, "collection_name", "legacy-collection")
    monkeypatch.setattr(retrieval_module.config, "CHROMA_PERSIST_DIR", str(tmp_path / "legacy"))
    monkeypatch.setattr(retrieval_module.config, "MODEL_EMBEDDING", "legacy-embedding")

    manifest = retrieval_module._load_index_manifest(binding)

    assert manifest.destination_collection == binding.collection_name
    assert manifest.persist_directory == str(persist)
    assert manifest.collection_revision == binding.revision


def test_rag_service_passes_binding_to_vector_store_without_external_services(monkeypatch, tmp_path):
    persist = tmp_path / "course-index"
    binding = CourseIndexBinding(
        collection_name="course-two",
        persist_directory=str(persist),
        manifest_path=str(tmp_path / "manifest.json"),
        revision="c" * 64,
        embedding_model="course-embedding",
    )
    manifest = SimpleNamespace(document_count=1, collection_revision=binding.revision)
    monkeypatch.setattr(retrieval_module, "_load_index_manifest", lambda actual: manifest)

    embedding_calls: list[dict] = []

    def fake_embedding(**kwargs):
        embedding_calls.append(kwargs)
        return object()

    monkeypatch.setattr(retrieval_module, "OpenAIEmbeddings", fake_embedding)
    monkeypatch.setattr(retrieval_module, "get_rag_text_model", lambda: object())
    monkeypatch.setattr(retrieval_module, "load_token_counter", lambda *_args: object())

    class FakeCollection:
        def count(self) -> int:
            return 1

    class FakeVectorStore:
        def __init__(self, *, embedding, collection_name, persist_directory):
            self.embedding = embedding
            self.collection_name = collection_name
            self.persist_directory = persist_directory
            self.collection = FakeCollection()

        def get_all_documents(self):
            return {"ids": ["chunk-1"], "documents": ["text"], "metadatas": [{}]}

        def close(self):
            return None

    monkeypatch.setattr(retrieval_module, "VectorStoreService", FakeVectorStore)

    service = RAGService(binding, course_name="第二门课程")

    assert service.index_binding == binding
    assert service._collection_name == "course-two"
    assert service._persist_directory == str(persist)
    assert embedding_calls[0]["model"] == "course-embedding"
    assert service.vector_store_service.collection_name == "course-two"
    assert service.vector_store_service.persist_directory == str(persist)
    prompt = service.prompt_template.invoke({"context": "课程材料", "input": "课程问题"})
    assert "《第二门课程》课程辅导" in prompt.messages[0].content


def test_digital_literacy_course_provides_its_published_index_binding():
    from ds_course_agent.courses import CourseCatalog

    manifest = CourseCatalog.from_directory("data/courses").require("digital-literacy")

    assert manifest.is_ready
    assert manifest.index_binding is not None
    assert manifest.index_binding.collection_name == "digital_literacy_7c516f878df0e9b2_student_v1"
    assert manifest.index_binding.metadata_schema_version == "retrieval-provenance/1.0"


def test_rag_prompt_uses_bound_course_display_name_and_keeps_default():
    digital_prompt = build_rag_prompt_template("数字素养与技能导论").invoke(
        {"context": "数字安全材料", "input": "什么是数字素养"}
    )
    default_prompt = build_rag_prompt_template().invoke({"context": "数据科学材料", "input": "什么是数据"})

    assert "《数字素养与技能导论》课程辅导" in digital_prompt.messages[0].content
    assert "《数据科学导论》课程辅导" in default_prompt.messages[0].content


def test_course_scoped_rag_services_do_not_mutate_default_singleton(monkeypatch):
    import ds_course_agent.tools._shared as shared_tools

    default_service = object()
    monkeypatch.setattr(shared_tools, "_rag_service", default_service)
    monkeypatch.setattr(shared_tools, "_course_rag_services", {})
    bindings = {"course-one": object(), "course-two": object()}
    manifests = {
        course_id: SimpleNamespace(index_binding=binding, display_name=f"课程-{course_id}")
        for course_id, binding in bindings.items()
    }
    monkeypatch.setattr(shared_tools, "_course_manifest", manifests.__getitem__)

    class FakeRAGService:
        def __init__(self, binding, *, course_name):
            self.binding = binding
            self.course_name = course_name

    monkeypatch.setattr("ds_course_agent.retrieval.service.RAGService", FakeRAGService)

    first = shared_tools.get_rag_service("course-one")
    second = shared_tools.get_rag_service("course-two")

    assert first is shared_tools.get_rag_service("course-one")
    assert second is shared_tools.get_rag_service("course-two")
    assert first is not second
    assert first.binding is bindings["course-one"]
    assert second.binding is bindings["course-two"]
    assert first.course_name == "课程-course-one"
    assert second.course_name == "课程-course-two"
    assert shared_tools._rag_service is default_service
