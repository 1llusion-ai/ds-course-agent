#!/usr/bin/env python3
"""Promote a course candidate into an isolated, provenance-verified index.

This promotion path is course-agnostic.  It copies the frozen candidate
vectors without re-embedding, reconstructs exact source-page intervals from
the saved Marker/cleaner output, and writes the production manifest consumed by
``RAGService``.  The destination remains under ``var/chroma_candidates`` until
an explicit course binding publishes it.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
import numpy as np
from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ds_course_agent.courses import CourseCatalog
from ds_course_agent.kb.cleaner import clean_document
from ds_course_agent.kb.ingestion import sanitize_text_for_storage
from ds_course_agent.retrieval.context_assembler import ChunkProvenance
from ds_course_agent.retrieval.index_manifest import IndexArtifact, PromotedIndexManifest
from scripts.build_course_candidate import _load_marker_intermediate

METADATA_SCHEMA_VERSION = "retrieval-provenance/1.0"
MAXIMUM_VECTOR_ABSOLUTE_ERROR = 1e-7
MINIMUM_VECTOR_COSINE_SIMILARITY = 0.999999


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content: str) -> str:
    return _sha256_bytes(content.encode("utf-8"))


def _normalize_text(text: str) -> str:
    return "".join(str(text or "").split())


def _artifact(path: Path) -> IndexArtifact:
    resolved = path.resolve()
    return IndexArtifact(
        path=resolved.relative_to(PROJECT_ROOT.resolve()).as_posix(),
        sha256=_sha256_bytes(resolved.read_bytes()),
    )


def _git_revision() -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return f"{commit}+dirty" if dirty else commit


def _source_page_map(marker_intermediate: Path, file_name: str) -> dict[int, str]:
    parsed = _load_marker_intermediate(marker_intermediate)
    pages = [
        (page.page_num, sanitize_text_for_storage(page.text))
        for page in parsed.pages
        if page.text and page.text.strip()
    ]
    cleaned = clean_document(pages, file_name)
    return {page.page_num: page.cleaned_text for page in cleaned.pages}


def _find_interval(page_text: str, content: str) -> tuple[int, int]:
    """Find a normalized content span and return raw-text character bounds."""
    normalized_page: list[str] = []
    raw_indices: list[int] = []
    for index, character in enumerate(page_text):
        if character.isspace():
            continue
        normalized_page.append(character)
        raw_indices.append(index)
    normalized = "".join(normalized_page)
    needle = _normalize_text(content)
    start = normalized.find(needle)
    if start < 0 or not needle:
        raise ValueError("candidate content cannot be located in the cleaned source page")
    end = start + len(needle)
    return raw_indices[start], raw_indices[end - 1] + 1


def _collection_payload(collection) -> dict[str, tuple[str, dict[str, Any], np.ndarray]]:
    payload = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = list(payload.get("ids") or [])
    documents = list(payload.get("documents") or [])
    metadatas = list(payload.get("metadatas") or [])
    embeddings = payload.get("embeddings")
    if embeddings is None:
        raise ValueError("candidate collection did not return embeddings")
    vectors = list(embeddings)
    if not (len(ids) == len(documents) == len(metadatas) == len(vectors)):
        raise ValueError("candidate collection returned inconsistent columns")
    return {
        str(chunk_id): (str(document or ""), dict(metadata or {}), np.asarray(vector, dtype=np.float32))
        for chunk_id, document, metadata, vector in zip(ids, documents, metadatas, vectors, strict=True)
    }


def _document_set_sha256(payload: dict[str, tuple[str, dict[str, Any], np.ndarray]]) -> str:
    digest = hashlib.sha256()
    for chunk_id in sorted(payload):
        digest.update(chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_text(payload[chunk_id][0]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _vectors_sha256(payload: dict[str, tuple[str, dict[str, Any], np.ndarray]]) -> str:
    digest = hashlib.sha256()
    for chunk_id in sorted(payload):
        digest.update(chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(np.asarray(payload[chunk_id][2], dtype="<f4").tobytes(order="C"))
    return digest.hexdigest()


def _production_metadata(
    *,
    document: str,
    candidate_metadata: dict[str, Any],
    source_page_text: str,
    source_id: str,
    source_page: int,
    book_page: int,
    collection_revision: str,
    course_name: str,
    source_file: str,
    created_at: str,
) -> dict[str, Any]:
    start, end = _find_interval(source_page_text, document)
    content_sha256 = _sha256_text(document)
    source_page_sha256 = _sha256_text(source_page_text)
    source_fragment = source_page_text[start:end]
    if _normalize_text(source_fragment) != _normalize_text(document):
        raise ValueError("source interval does not reproduce candidate content")
    metadata = dict(candidate_metadata)
    metadata.update(
        {
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
            "collection_revision": collection_revision,
            "course": course_name,
            "source": source_file,
            "source_id": source_id,
            "source_page": source_page,
            "source_page_start": source_page,
            "source_page_end": source_page,
            "book_page": book_page,
            "book_page_start": book_page,
            "book_page_end": book_page,
            "page": book_page,
            "page_start": book_page,
            "page_end": book_page,
            "source_char_start": start,
            "source_char_end": end,
            "content_sha256": content_sha256,
            "source_page_sha256": source_page_sha256,
            "source_page_text": source_page_text,
            "chunk_id": str(candidate_metadata.get("chunk_id") or ""),
            "chunk_type": "semantic",
            "parser_source": str(candidate_metadata.get("parser_source") or "marker"),
            "ingest_time": created_at,
        }
    )
    if not metadata["chunk_id"]:
        raise ValueError("candidate metadata is missing chunk_id")
    ChunkProvenance.from_document(Document(page_content=document, metadata=metadata))
    return metadata


def promote_course_candidate(
    *,
    candidate_root: Path,
    marker_intermediate: Path,
    output: Path,
    destination_collection: str,
    code_revision: str | None = None,
    now: datetime | None = None,
) -> PromotedIndexManifest:
    """Promote one course candidate while preserving exact vectors and provenance."""
    candidate_root = candidate_root.resolve()
    marker_intermediate = marker_intermediate.resolve(strict=True)
    output = output.resolve()
    candidate_root.relative_to((PROJECT_ROOT / "var" / "chroma_candidates").resolve())
    if not output.is_relative_to((PROJECT_ROOT / "var" / "chroma_candidates").resolve()):
        raise ValueError("promotion output must be under var/chroma_candidates")
    if output.exists():
        raise ValueError("promotion output already exists; refusing overwrite")
    if not destination_collection.strip():
        raise ValueError("destination collection must be non-empty")

    candidate_manifest_path = candidate_root / "candidate_index_manifest.json"
    bundle_path = candidate_root / "chunks.json"
    candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if candidate_manifest.get("status") != "unready" or candidate_manifest.get("published") is not False:
        raise ValueError("candidate must remain unready and unpublished before promotion")
    course_id = str(candidate_manifest["course_id"])
    course = CourseCatalog.from_directory(PROJECT_ROOT / "data" / "courses").require(course_id)
    if course.index is not None or course.is_ready:
        raise ValueError("course already has a published index binding")
    course_name = course.display_name
    page_offset = int(course.resource_metadata.get("page_offset", 0))
    source_file = Path(candidate_manifest["source"]["path"]).name
    source_pages = _source_page_map(marker_intermediate, source_file)
    chunks = list(bundle.get("chunks") or [])
    if len(chunks) != int(candidate_manifest["chunk_count"]):
        raise ValueError("candidate chunk count does not match its bundle")
    source_persist = candidate_root / "chroma"
    source_client = chromadb.PersistentClient(path=str(source_persist))
    source_collection = source_client.get_collection(candidate_manifest["collection_name"])
    source_payload = _collection_payload(source_collection)
    collection_metadata = dict(source_collection.metadata or {})
    if collection_metadata.get("hnsw:space") != "cosine":
        raise ValueError("candidate collection must use cosine distance")
    vector_dimension = int(candidate_manifest["embedding"]["dimension"])
    if any(len(vector) != vector_dimension for _, _, vector in source_payload.values()):
        raise ValueError("candidate vector dimension differs from its manifest")

    # The course candidate bundle intentionally stores semantic chunk metadata,
    # while Chroma owns the stable content hash IDs.  Join them by immutable
    # evidence fields instead of relying on list order.
    chunk_by_id: dict[str, dict[str, Any]] = {}
    used_ids: set[str] = set()
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        source_pages_value = json.dumps(metadata.get("source_pages") or [], ensure_ascii=False)
        candidates = [
            chunk_id
            for chunk_id, (document, stored_metadata, _vector) in source_payload.items()
            if chunk_id not in used_ids
            and document == str(chunk.get("content") or "")
            and stored_metadata.get("source_pages") == source_pages_value
            and stored_metadata.get("heading_path", "") == str(metadata.get("heading_path") or "")
        ]
        if len(candidates) != 1:
            raise ValueError(f"candidate bundle cannot be joined to exactly one Chroma row: {candidates}")
        chunk_id = candidates[0]
        used_ids.add(chunk_id)
        chunk_by_id[chunk_id] = chunk
    if set(source_payload) != set(chunk_by_id):
        raise ValueError("candidate Chroma IDs differ from the chunk bundle")

    created_at = (now or datetime.now(timezone.utc)).isoformat()
    collection_revision = str(candidate_manifest["revision"])
    started = time.perf_counter()
    temporary_root = Path(tempfile.mkdtemp(prefix=".course-production-", dir=output.parent))
    try:
        destination_client = chromadb.PersistentClient(path=str(temporary_root / "chroma"))
        destination = destination_client.create_collection(
            destination_collection,
            metadata={"hnsw:space": "cosine"},
        )
        for offset in range(0, len(chunks), 64):
            batch = chunks[offset : offset + 64]
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []
            vectors: list[list[float]] = []
            ids: list[str] = []
            for chunk in batch:
                chunk_id = next(
                    candidate_id for candidate_id, candidate_chunk in chunk_by_id.items() if candidate_chunk is chunk
                )
                document, candidate_metadata, vector = source_payload[chunk_id]
                raw_source_pages = chunk["metadata"].get("source_pages") or []
                raw_book_pages = chunk["metadata"].get("book_pages") or []
                if len(raw_source_pages) != 1 or len(raw_book_pages) != 1:
                    raise ValueError(f"chunk {chunk_id} lacks a single exact source page")
                source_page = int(raw_source_pages[0])
                book_page = int(raw_book_pages[0])
                if book_page != source_page + page_offset:
                    raise ValueError(f"course page mapping drift for {chunk_id}")
                if source_page not in source_pages:
                    raise ValueError(f"source page {source_page} is absent from Marker output")
                metadata = _production_metadata(
                    document=document,
                    candidate_metadata=candidate_metadata,
                    source_page_text=source_pages[source_page],
                    source_id=source_file,
                    source_page=source_page,
                    book_page=book_page,
                    collection_revision=collection_revision,
                    course_name=course_name,
                    source_file=source_file,
                    created_at=created_at,
                )
                documents.append(document)
                metadatas.append(metadata)
                vectors.append(vector.tolist())
                ids.append(chunk_id)
            destination.add(ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas)

        destination_payload = _collection_payload(destination)
        if set(destination_payload) != set(source_payload) or destination.count() != len(chunks):
            raise ValueError("promoted collection count or IDs differ from the candidate")
        maximum_vector_error = 0.0
        minimum_vector_cosine = 1.0
        for chunk_id, (source_document, _, source_vector) in source_payload.items():
            destination_document, destination_metadata, destination_vector = destination_payload[chunk_id]
            if destination_document != source_document:
                raise ValueError(f"promoted document content changed for {chunk_id}")
            maximum_vector_error = max(
                maximum_vector_error,
                float(np.max(np.abs(destination_vector - source_vector))),
            )
            denominator = float(np.linalg.norm(source_vector) * np.linalg.norm(destination_vector))
            cosine_similarity = float(np.dot(source_vector, destination_vector) / denominator)
            minimum_vector_cosine = min(minimum_vector_cosine, cosine_similarity)
        if maximum_vector_error > MAXIMUM_VECTOR_ABSOLUTE_ERROR:
            raise ValueError("promoted vector exceeds absolute-error tolerance")
        if minimum_vector_cosine < MINIMUM_VECTOR_COSINE_SIMILARITY:
            raise ValueError("promoted vector exceeds cosine-similarity tolerance")

        manifest = PromotedIndexManifest(
            schema_version="retrieval-production-index/1.0",
            created_at=now or datetime.now(timezone.utc),
            candidate_bundle=_artifact(bundle_path),
            candidate_index_manifest=_artifact(candidate_manifest_path),
            source_collection=str(candidate_manifest["collection_name"]),
            destination_collection=destination_collection,
            persist_directory=(output / "chroma").relative_to(PROJECT_ROOT).as_posix(),
            document_count=len(chunks),
            vector_dimension=vector_dimension,
            embedding_model=str(candidate_manifest["embedding"]["model"]),
            embedding_distance="cosine",
            embedding_query_prefix="",
            metadata_schema_version=METADATA_SCHEMA_VERSION,
            collection_revision=collection_revision,
            document_set_sha256=_document_set_sha256(destination_payload),
            source_vectors_sha256=_vectors_sha256(source_payload),
            destination_vectors_sha256=_vectors_sha256(destination_payload),
            maximum_vector_absolute_error=maximum_vector_error,
            minimum_vector_cosine_similarity=minimum_vector_cosine,
            code_revision=code_revision or _git_revision(),
            build_seconds=time.perf_counter() - started,
        )
        (temporary_root / "production_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        destination_client.close()
        os.replace(temporary_root, output)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    finally:
        source_client.close()
        gc.collect()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--marker-intermediate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection-name", required=True)
    parser.add_argument("--code-revision")
    args = parser.parse_args()
    manifest = promote_course_candidate(
        candidate_root=args.candidate_root,
        marker_intermediate=args.marker_intermediate,
        output=args.output,
        destination_collection=args.collection_name,
        code_revision=args.code_revision,
    )
    print(manifest.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
