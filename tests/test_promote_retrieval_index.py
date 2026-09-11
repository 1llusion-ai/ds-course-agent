"""Tests for deterministic promotion of a frozen retrieval candidate."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import pytest

from benchmarks.retrieval_candidate_schema import (
    CandidateChunk,
    CandidateChunkBundle,
    CandidateDiagnostics,
    CandidateIndexManifest,
    ChunkCandidateSpec,
    EmbeddingIndexSpec,
)
from benchmarks.retrieval_gold_schema import Artifact, SourceManifest, SourcePage, canonical_sha256
from scripts.promote_retrieval_index import promote_index


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(root: Path, relative: str, content: bytes) -> Artifact:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return Artifact(path=relative, sha256=_sha256(content))


def _build_candidate(root: Path) -> tuple[Path, Path]:
    source_text = "abcdefghij"
    page = SourcePage(
        source_id="book",
        source_page=9,
        book_page=1,
        text=source_text,
        text_sha256=_sha256(source_text.encode()),
        role="body",
    )
    pages = _write(root, "var/artifacts/source_pages.jsonl", (page.model_dump_json() + "\n").encode())
    pdf = _write(root, "data/book.pdf", b"pdf")
    parse_cache = _write(root, "var/cache/parse.pkl", b"parse")
    clean_cache = _write(root, "var/cache/clean.pkl", b"clean")
    atomic_units = _write(root, "var/artifacts/atomic_units.json", b"[]\n")
    source_manifest = SourceManifest(
        source_id="book",
        pdf=pdf,
        parse_cache=parse_cache,
        clean_cache=clean_cache,
        pages_export=pages,
        atomic_units=atomic_units,
        total_pages=248,
        book_page_offset=-8,
        parser_mode="marker-test",
        cleaner_version="clean-test",
        exporter_version="export-test",
        git_commit="0" * 40,
        working_tree_dirty=False,
        code_files=[],
    )
    source_manifest_path = root / "var/artifacts/source_manifest.json"
    source_manifest_path.write_text(source_manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    source_manifest_artifact = Artifact(
        path=source_manifest_path.relative_to(root).as_posix(),
        sha256=_sha256(source_manifest_path.read_bytes()),
    )
    chunker = _write(root, "src/chunker.py", b"# test\n")
    content = source_text[2:8]
    chunk = CandidateChunk(
        id="chunk-1",
        content=content,
        content_sha256=_sha256(content.encode()),
        source_id="book",
        source_page=9,
        book_page=1,
        source_start=2,
        source_end=8,
        mapping_method="remove_whitespace_v1",
        chapter="第一章",
        chapter_number="第1章",
        section="测试",
        section_number="1.1",
        subsection="",
        subsection_number="",
    )
    bundle = CandidateChunkBundle(
        schema_version="retrieval-candidate-chunks/1.0",
        created_at=datetime.now(timezone.utc),
        source_manifest=source_manifest_artifact,
        source_manifest_canonical_sha256=canonical_sha256(source_manifest),
        chunker=chunker,
        candidate=ChunkCandidateSpec(id="fine_test", chunk_size=700, chunk_overlap=140, max_chunk_size=900),
        diagnostics=CandidateDiagnostics(
            body_page_count=1,
            semantic_chunk_count=1,
            average_chunk_characters=float(len(content)),
            maximum_chunk_characters=len(content),
            ambiguous_mapping_count=0,
            atomic_unit_count=0,
            intact_atomic_unit_count=0,
        ),
        chunks=[chunk],
    )
    bundle_path = root / "var/chroma_candidates/source/chunks.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")

    source_persist = root / "var/chroma_candidates/source/index/chroma"
    client = chromadb.PersistentClient(path=str(source_persist))
    collection = client.create_collection("retrieval_fine_test_qwen", metadata={"hnsw:space": "cosine"})
    collection.add(ids=[chunk.id], documents=[chunk.content], embeddings=[[0.25, 0.75]], metadatas=[{"old": "x"}])
    client.close()
    manifest = CandidateIndexManifest(
        schema_version="retrieval-candidate-index/1.0",
        created_at=datetime.now(timezone.utc),
        candidate_bundle=Artifact(
            path=bundle_path.relative_to(root).as_posix(),
            sha256=_sha256(bundle_path.read_bytes()),
        ),
        embedding=EmbeddingIndexSpec(
            id="qwen_test",
            model="Qwen/Qwen3-Embedding-8B",
            dimensions=None,
            distance="cosine",
            query_prefix="",
            batch_size=1,
        ),
        persist_directory=source_persist.relative_to(root).as_posix(),
        collection_name=collection.name,
        document_count=1,
        vector_dimension=2,
        build_seconds=0.1,
    )
    manifest_path = root / "var/chroma_candidates/source/index/index_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle_path, manifest_path


def test_promote_index_preserves_documents_vectors_and_exact_provenance(tmp_path):
    bundle_path, manifest_path = _build_candidate(tmp_path)
    output = tmp_path / "var/chroma_candidates/promoted"

    manifest = promote_index(
        root=tmp_path,
        bundle_path=bundle_path,
        candidate_manifest_path=manifest_path,
        output=output,
        destination_collection="rag_knowledge_base",
        expected_bundle_sha256=_sha256(bundle_path.read_bytes()),
        expected_manifest_sha256=_sha256(manifest_path.read_bytes()),
        code_revision="test-revision",
        now=datetime.now(timezone.utc),
    )

    assert manifest.document_count == 1
    assert manifest.vector_dimension == 2
    assert manifest.embedding_model == "Qwen/Qwen3-Embedding-8B"
    assert manifest.maximum_vector_absolute_error <= 1e-7
    assert manifest.minimum_vector_cosine_similarity >= 0.999999
    assert (output / "production_manifest.json").is_file()
    client = chromadb.PersistentClient(path=str(output / "chroma"))
    collection = client.get_collection("rag_knowledge_base")
    payload = collection.get(include=["documents", "metadatas", "embeddings"])
    metadata = payload["metadatas"][0]
    assert payload["ids"] == ["chunk-1"]
    assert payload["documents"] == ["cdefgh"]
    assert list(payload["embeddings"][0]) == pytest.approx([0.25, 0.75])
    assert metadata["source_page"] == 9
    assert metadata["book_page"] == 1
    assert metadata["source_char_start"] == 2
    assert metadata["source_char_end"] == 8
    assert metadata["source_page_text"] == "abcdefghij"
    assert metadata["content_sha256"] == _sha256(b"cdefgh")
    client.close()


def test_promote_index_rejects_active_database_output(tmp_path):
    bundle_path, manifest_path = _build_candidate(tmp_path)

    with pytest.raises(ValueError, match="outside var/chroma_db"):
        promote_index(
            root=tmp_path,
            bundle_path=bundle_path,
            candidate_manifest_path=manifest_path,
            output=tmp_path / "var/chroma_db/new",
            destination_collection="rag_knowledge_base",
            expected_bundle_sha256=_sha256(bundle_path.read_bytes()),
            expected_manifest_sha256=_sha256(manifest_path.read_bytes()),
            code_revision="test-revision",
        )
