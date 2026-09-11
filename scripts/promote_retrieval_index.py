"""Promote the frozen retrieval winner into a verified production-shaped index."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
import numpy as np

from benchmarks.retrieval_candidate_schema import CandidateChunkBundle, CandidateIndexManifest
from benchmarks.retrieval_gold_schema import SourceManifest, SourcePage
from benchmarks.retrieval_gold_validation import artifact_bytes
from ds_course_agent.retrieval.index_manifest import IndexArtifact, PromotedIndexManifest

FROZEN_BUNDLE = Path("var/chroma_candidates/chunk_eval_20260910/fine_700_140/chunks.json")
FROZEN_BUNDLE_SHA256 = "209061230b2ac4ea2f8bd54188f8694f4a4574aa4ee5618a57f39de2c8ec6a2b"
FROZEN_INDEX_MANIFEST = Path(
    "var/chroma_candidates/chunk_eval_20260910/fine_700_140/indexes/qwen3_8b_native/index_manifest.json"
)
FROZEN_INDEX_MANIFEST_SHA256 = "2d8684c1aa5cc3b8c92264ed2205f14f7792d0afccbda30c5daf9bd40b664c3b"
EXPECTED_DOCUMENT_COUNT = 313
EXPECTED_VECTOR_DIMENSION = 4096
EXPECTED_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
METADATA_SCHEMA_VERSION = "retrieval-provenance/1.0"
MAXIMUM_VECTOR_ABSOLUTE_ERROR = 1e-7
MINIMUM_VECTOR_COSINE_SIMILARITY = 0.999999


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content: str) -> str:
    return _sha256_bytes(content.encode("utf-8"))


def _artifact(root: Path, path: Path) -> IndexArtifact:
    resolved = path.resolve()
    return IndexArtifact(
        path=resolved.relative_to(root.resolve()).as_posix(),
        sha256=_sha256_bytes(resolved.read_bytes()),
    )


def _require_hash(path: Path, expected: str) -> None:
    actual = _sha256_bytes(path.read_bytes())
    if actual != expected:
        raise ValueError(f"artifact hash mismatch for {path}: expected {expected}, got {actual}")


def _normalize_text(text: str) -> str:
    return "".join(str(text or "").split())


def _load_source_pages(
    root: Path, bundle: CandidateChunkBundle
) -> tuple[SourceManifest, dict[tuple[str, int], SourcePage]]:
    source_manifest_path = root / bundle.source_manifest.path
    if _sha256_bytes(source_manifest_path.read_bytes()) != bundle.source_manifest.sha256:
        raise ValueError("candidate bundle source manifest hash is stale")
    source_manifest = SourceManifest.model_validate_json(source_manifest_path.read_bytes())
    pages = [
        SourcePage.model_validate_json(line)
        for line in artifact_bytes(root, source_manifest.pages_export).decode("utf-8").splitlines()
    ]
    return source_manifest, {(page.source_id, page.source_page): page for page in pages}


def _production_metadata(
    *,
    chunk,
    page: SourcePage,
    source_manifest: SourceManifest,
    source_file: str,
    collection_revision: str,
    created_at: datetime,
) -> dict[str, Any]:
    if chunk.book_page != chunk.source_page - 8:
        raise ValueError(f"book/source page mapping drift for {chunk.id}")
    if page.book_page != chunk.book_page:
        raise ValueError(f"source export page mapping drift for {chunk.id}")
    if page.text_sha256 != _sha256_text(page.text):
        raise ValueError(f"source page text hash is stale for {chunk.id}")
    source_fragment = page.text[chunk.source_start : chunk.source_end]
    if _normalize_text(source_fragment) != _normalize_text(chunk.content):
        raise ValueError(f"source interval does not reproduce normalized chunk content for {chunk.id}")
    if _sha256_text(chunk.content) != chunk.content_sha256:
        raise ValueError(f"candidate content hash is stale for {chunk.id}")

    return {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "collection_revision": collection_revision,
        "course": "数据科学导论",
        "source": source_file,
        "source_id": chunk.source_id,
        "source_page": chunk.source_page,
        "source_page_start": chunk.source_page,
        "source_page_end": chunk.source_page,
        "book_page": chunk.book_page,
        "book_page_start": chunk.book_page,
        "book_page_end": chunk.book_page,
        "page": chunk.book_page,
        "page_start": chunk.book_page,
        "page_end": chunk.book_page,
        "source_char_start": chunk.source_start,
        "source_char_end": chunk.source_end,
        "content_sha256": chunk.content_sha256,
        "source_page_sha256": page.text_sha256,
        "source_page_text": page.text,
        "chunk_id": chunk.id,
        "chunk_type": "semantic",
        "chunker_id": "fine_700_140",
        "parser_source": source_manifest.parser_mode,
        "chapter": chunk.chapter,
        "chapter_no": chunk.chapter_number,
        "section": chunk.section,
        "section_no": chunk.section_number,
        "subsection": chunk.subsection,
        "subsection_no": chunk.subsection_number,
        "ingest_time": created_at.isoformat(),
    }


def _git_revision(root: Path) -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return f"{commit}+dirty" if dirty else commit


def _collection_payload(collection) -> dict[str, Any]:
    payload = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = list(payload.get("ids") or [])
    documents = list(payload.get("documents") or [])
    metadatas = list(payload.get("metadatas") or [])
    embeddings = payload.get("embeddings")
    if embeddings is None:
        raise ValueError("Chroma collection did not return embeddings")
    vectors = list(embeddings)
    if not (len(ids) == len(documents) == len(metadatas) == len(vectors)):
        raise ValueError("Chroma collection returned inconsistent column lengths")
    return {
        str(chunk_id): (str(document or ""), dict(metadata or {}), np.asarray(vector, dtype=np.float32))
        for chunk_id, document, metadata, vector in zip(ids, documents, metadatas, vectors, strict=True)
    }


def _document_set_sha256(payload: dict[str, tuple[str, dict[str, Any], np.ndarray]]) -> str:
    digest = hashlib.sha256()
    for chunk_id in sorted(payload):
        document = payload[chunk_id][0]
        digest.update(chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_text(document).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _vectors_sha256(payload: dict[str, tuple[str, dict[str, Any], np.ndarray]]) -> str:
    digest = hashlib.sha256()
    for chunk_id in sorted(payload):
        vector = np.asarray(payload[chunk_id][2], dtype="<f4")
        digest.update(chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(vector.tobytes(order="C"))
    return digest.hexdigest()


def promote_index(
    *,
    root: Path,
    bundle_path: Path,
    candidate_manifest_path: Path,
    output: Path,
    destination_collection: str,
    expected_bundle_sha256: str,
    expected_manifest_sha256: str,
    code_revision: str,
    now: datetime | None = None,
) -> PromotedIndexManifest:
    """Create and verify a fresh production-shaped index without re-embedding."""
    root = root.resolve()
    bundle_path = bundle_path.resolve()
    candidate_manifest_path = candidate_manifest_path.resolve()
    output = output.resolve()
    candidate_root = root / "var" / "chroma_candidates"
    active_root = root / "var" / "chroma_db"
    if not output.is_relative_to(candidate_root) or output.is_relative_to(active_root):
        raise ValueError("promotion output must be under var/chroma_candidates and outside var/chroma_db")
    if output.exists():
        raise ValueError("promotion output already exists; refusing overwrite")
    if not destination_collection.strip():
        raise ValueError("destination collection must be non-empty")

    _require_hash(bundle_path, expected_bundle_sha256)
    _require_hash(candidate_manifest_path, expected_manifest_sha256)
    bundle = CandidateChunkBundle.model_validate_json(bundle_path.read_bytes())
    candidate_manifest = CandidateIndexManifest.model_validate_json(candidate_manifest_path.read_bytes())
    if candidate_manifest.candidate_bundle.path != bundle_path.relative_to(root).as_posix():
        raise ValueError("candidate index manifest points at a different chunk bundle")
    if candidate_manifest.candidate_bundle.sha256 != expected_bundle_sha256:
        raise ValueError("candidate index manifest contains a stale chunk bundle hash")
    if candidate_manifest.document_count != len(bundle.chunks):
        raise ValueError("candidate document count differs from the chunk bundle")
    if candidate_manifest.embedding.model != EXPECTED_EMBEDDING_MODEL:
        raise ValueError("candidate index does not use the frozen embedding model")
    if candidate_manifest.embedding.query_prefix:
        raise ValueError("candidate index unexpectedly declares a query instruction")
    if candidate_manifest.embedding.distance != "cosine":
        raise ValueError("candidate index does not use cosine distance")

    source_manifest, source_pages = _load_source_pages(root, bundle)
    if source_manifest.book_page_offset != -8:
        raise ValueError("production promotion requires book_page = source_page - 8")
    source_file = Path(source_manifest.pdf.path).name
    collection_revision = _sha256_text(f"{expected_bundle_sha256}|{expected_manifest_sha256}")
    created_at = now or datetime.now().astimezone()

    source_persist = root / candidate_manifest.persist_directory
    source_client = chromadb.PersistentClient(path=str(source_persist))
    source_collection = source_client.get_collection(candidate_manifest.collection_name)
    source_payload = _collection_payload(source_collection)
    chunk_by_id = {chunk.id: chunk for chunk in bundle.chunks}
    if set(source_payload) != set(chunk_by_id):
        raise ValueError("candidate Chroma IDs differ from the frozen chunk bundle")
    if any(len(vector) != candidate_manifest.vector_dimension for _, _, vector in source_payload.values()):
        raise ValueError("candidate Chroma vector dimension differs from its manifest")

    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    temporary_root = Path(tempfile.mkdtemp(prefix=".retrieval-production-", dir=output.parent))
    try:
        persist = temporary_root / "chroma"
        destination_client = chromadb.PersistentClient(path=str(persist))
        destination = destination_client.create_collection(
            destination_collection,
            metadata={"hnsw:space": "cosine"},
        )
        for offset in range(0, len(bundle.chunks), 64):
            batch = bundle.chunks[offset : offset + 64]
            destination.add(
                ids=[chunk.id for chunk in batch],
                documents=[source_payload[chunk.id][0] for chunk in batch],
                embeddings=[source_payload[chunk.id][2].tolist() for chunk in batch],
                metadatas=[
                    _production_metadata(
                        chunk=chunk,
                        page=source_pages[(chunk.source_id, chunk.source_page)],
                        source_manifest=source_manifest,
                        source_file=source_file,
                        collection_revision=collection_revision,
                        created_at=created_at,
                    )
                    for chunk in batch
                ],
            )

        destination_payload = _collection_payload(destination)
        if destination.count() != len(bundle.chunks) or set(destination_payload) != set(source_payload):
            raise ValueError("promoted index document IDs/count differ from the frozen candidate")
        maximum_vector_error = 0.0
        minimum_vector_cosine = 1.0
        for chunk_id, (source_document, _, source_vector) in source_payload.items():
            destination_document, destination_metadata, destination_vector = destination_payload[chunk_id]
            if destination_document != source_document:
                raise ValueError(f"promoted document content changed for {chunk_id}")
            if destination_metadata.get("content_sha256") != chunk_by_id[chunk_id].content_sha256:
                raise ValueError(f"promoted document hash metadata changed for {chunk_id}")
            maximum_vector_error = max(
                maximum_vector_error,
                float(np.max(np.abs(destination_vector - source_vector))),
            )
            denominator = float(np.linalg.norm(source_vector) * np.linalg.norm(destination_vector))
            cosine_similarity = float(np.dot(source_vector, destination_vector) / denominator)
            minimum_vector_cosine = min(minimum_vector_cosine, cosine_similarity)
            if maximum_vector_error > MAXIMUM_VECTOR_ABSOLUTE_ERROR:
                raise ValueError(f"promoted vector exceeds absolute-error tolerance for {chunk_id}")
            if cosine_similarity < MINIMUM_VECTOR_COSINE_SIMILARITY:
                raise ValueError(f"promoted vector exceeds cosine-similarity tolerance for {chunk_id}")

        manifest = PromotedIndexManifest(
            schema_version="retrieval-production-index/1.0",
            created_at=created_at,
            candidate_bundle=_artifact(root, bundle_path),
            candidate_index_manifest=_artifact(root, candidate_manifest_path),
            source_collection=candidate_manifest.collection_name,
            destination_collection=destination_collection,
            persist_directory=(output / "chroma").relative_to(root).as_posix(),
            document_count=len(bundle.chunks),
            vector_dimension=candidate_manifest.vector_dimension,
            embedding_model=candidate_manifest.embedding.model,
            embedding_distance=candidate_manifest.embedding.distance,
            embedding_query_prefix=candidate_manifest.embedding.query_prefix,
            metadata_schema_version=METADATA_SCHEMA_VERSION,
            collection_revision=collection_revision,
            document_set_sha256=_document_set_sha256(destination_payload),
            source_vectors_sha256=_vectors_sha256(source_payload),
            destination_vectors_sha256=_vectors_sha256(destination_payload),
            maximum_vector_absolute_error=maximum_vector_error,
            minimum_vector_cosine_similarity=minimum_vector_cosine,
            code_revision=code_revision,
            build_seconds=time.perf_counter() - started,
        )
        (temporary_root / "production_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        del destination, destination_client
        gc.collect()
        os.replace(temporary_root, output)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise

    del source_collection, source_client
    gc.collect()
    return manifest


def main() -> int:
    """Promote the exact frozen winner into a user-selected isolated directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=FROZEN_BUNDLE)
    parser.add_argument("--candidate-index-manifest", type=Path, default=FROZEN_INDEX_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection-name", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = promote_index(
        root=args.root,
        bundle_path=args.bundle,
        candidate_manifest_path=args.candidate_index_manifest,
        output=args.output,
        destination_collection=args.collection_name,
        expected_bundle_sha256=FROZEN_BUNDLE_SHA256,
        expected_manifest_sha256=FROZEN_INDEX_MANIFEST_SHA256,
        code_revision=_git_revision(args.root.resolve()),
    )
    if manifest.document_count != EXPECTED_DOCUMENT_COUNT:
        raise ValueError("frozen production promotion did not produce 313 documents")
    if manifest.vector_dimension != EXPECTED_VECTOR_DIMENSION:
        raise ValueError("frozen production promotion did not preserve 4096-dimensional vectors")
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
