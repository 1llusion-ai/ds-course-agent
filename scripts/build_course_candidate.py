#!/usr/bin/env python3
"""Build an isolated course retrieval candidate without publishing it.

The command is deliberately separate from the student runtime.  It uses the
existing Marker parser, cleaner, and ``CourseChunkerV2`` before embedding into
a course-specific Chroma collection under ``var/chroma_candidates``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._path import ensure_src_path  # noqa: E402

ensure_src_path()

import ds_course_agent.shared.config as config  # noqa: E402
from ds_course_agent.courses import CourseCatalog, CourseResourceManifest  # noqa: E402
from ds_course_agent.kb.chunker import CourseChunkerV2  # noqa: E402
from ds_course_agent.kb.cleaner import clean_document  # noqa: E402
from ds_course_agent.kb.ingestion import sanitize_text_for_storage  # noqa: E402
from ds_course_agent.kb.parser import PageResult, ParsedBlock, ParserMode, PDFParseResult, parse_pdf_file  # noqa: E402
from ds_course_agent.kb.store import CourseKnowledgeBase, sanitize_collection_name  # noqa: E402
from ds_course_agent.kb.toc_parser import TOCParser  # noqa: E402
from ds_course_agent.shared.paths import PROJECT_ROOT as PACKAGE_ROOT  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "course"


def _revision(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_json(value):
    if isinstance(value, str):
        return sanitize_text_for_storage(value)
    if isinstance(value, dict):
        return {_safe_json(str(key)): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return value


def _manifest(course_id: str) -> CourseResourceManifest:
    return CourseCatalog.from_directory(PACKAGE_ROOT / "data" / "courses").require(course_id)


def _load_marker_intermediate(path: Path) -> PDFParseResult:
    """Load a saved local Marker result while retaining the formal parse types."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    pages = []
    for raw_page in payload.get("pages", []):
        blocks = [
            ParsedBlock(
                block_type=str(block.get("block_type", "")),
                text=str(block.get("text", "")),
                block_id=str(block.get("block_id", "")),
                bbox=tuple(block["bbox"]) if block.get("bbox") else None,
                section_hierarchy=tuple(tuple(item) for item in block.get("section_hierarchy", [])),
            )
            for block in raw_page.get("blocks", [])
        ]
        pages.append(
            PageResult(
                page_num=int(raw_page["page_num"]),
                text=str(raw_page.get("text", "")),
                parser="marker",
                char_count=int(raw_page.get("char_count", 0)),
                original_char_count=int(raw_page.get("original_char_count", 0)),
                error=raw_page.get("error"),
                blocks=blocks,
            )
        )
    return PDFParseResult(
        file_name=str(payload.get("file_name", "digital-literacy-course.pdf")),
        total_pages=int(payload.get("total_pages", len(pages))),
        pages=pages,
        marker_pages=int(payload.get("marker_pages", len(pages))),
        success_rate=float(payload.get("success_rate", 1.0)),
        full_text=str(payload.get("full_text", "")),
        parser_mode="marker",
        error=payload.get("error"),
    )


def build_candidate(
    *,
    course_id: str,
    source: Path,
    parser_mode: ParserMode = "marker",
    persist_directory: Path | None = None,
    collection_name: str | None = None,
    embedding_model: str | None = None,
    candidate_dir: str | None = None,
    marker_intermediate: Path | None = None,
    no_cache: bool = False,
) -> dict:
    """Parse, clean, chunk, embed, and verify one isolated candidate index."""

    if parser_mode != "marker":
        raise ValueError("正式课程候选索引必须显式使用 parser_mode=marker")
    source = source.resolve(strict=True)
    source_root = (PACKAGE_ROOT / "var" / "course_sources").resolve()
    try:
        source.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("source must be under var/course_sources") from exc
    if source.suffix.lower() != ".pdf":
        raise ValueError("source must be a PDF")

    course = _manifest(course_id)
    source_sha256 = _sha256(source)
    version = f"sha256-{source_sha256[:16]}"
    model_name = str(embedding_model or config.EMBEDDING_MODEL)
    model_slug = _slug(model_name)
    root = PACKAGE_ROOT / "var" / "chroma_candidates" / str(course.course_id) / version / (candidate_dir or model_slug)
    persist = (persist_directory or root / "chroma").resolve()
    candidate_collection = sanitize_collection_name(
        collection_name or f"{course.course_id}_{version[-16:]}_{candidate_dir or model_slug}"
    )
    if not persist.is_relative_to((PACKAGE_ROOT / "var" / "chroma_candidates").resolve()):
        raise ValueError("candidate persist directory must be under var/chroma_candidates")

    started = time.perf_counter()
    if marker_intermediate is not None:
        marker_intermediate = marker_intermediate.resolve(strict=True)
        parse_result = _load_marker_intermediate(marker_intermediate)
        parse_provenance = marker_intermediate.relative_to(PACKAGE_ROOT).as_posix()
    else:
        parse_result = parse_pdf_file(str(source), parser_mode=parser_mode, save_trace=False)
        parse_provenance = "local_marker_runtime"
    if parse_result.error or not parse_result.pages:
        raise RuntimeError(parse_result.error or "Marker returned no pages")

    pages = [
        (page.page_num, sanitize_text_for_storage(page.text))
        for page in parse_result.pages
        if page.text and page.text.strip()
    ]
    cleaned = clean_document(pages, parse_result.file_name)
    toc_path = PACKAGE_ROOT / course.toc_path
    toc = TOCParser(str(toc_path)) if course.toc_path else TOCParser()
    page_offset = int(course.resource_metadata.get("page_offset", 0))
    chunk_result = CourseChunkerV2(toc).chunk_document(
        [(page.page_num, page.cleaned_text) for page in cleaned.pages],
        parse_result.file_name,
        parser_source=parse_result.parser_mode,
        page_offset=page_offset,
        heading_hints={
            page.page_num: tuple(block.text for block in page.blocks if block.block_type == "SectionHeader")
            for page in parse_result.pages
        },
    )
    if not chunk_result.chunks:
        raise RuntimeError("Marker/cleaner/chunker produced no chunks")

    persist.mkdir(parents=True, exist_ok=True)
    chunk_digest = hashlib.sha256(
        json.dumps(
            [_safe_json(asdict(chunk)) for chunk in chunk_result.chunks if chunk.metadata.chunk_type == "semantic"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    revision = _revision(
        {
            "course_id": str(course.course_id),
            "source_sha256": source_sha256,
            "parser_mode": parser_mode,
            "embedding_model": model_name,
            "collection_name": candidate_collection,
            "document_count": chunk_result.semantic_chunks,
            "chunk_policy": "section-boundaries-v4",
            "chunk_digest": chunk_digest,
        }
    )
    kb = CourseKnowledgeBase(
        course_name=course.display_name,
        collection_name=candidate_collection,
        persist_directory=str(persist),
        embedding_model=model_name,
        metadata_context={
            "course_id": str(course.course_id),
            "resource_version": version,
            "source_sha256": source_sha256,
            "collection_revision": revision,
        },
        collection_metadata={"hnsw:space": "cosine"},
    )
    ingest = kb.ingest_chunking_result(chunk_result, source_file=parse_result.file_name)
    status = kb.get_status()

    collection = kb.vector_store._collection
    collection_metadata = dict(collection.metadata or {})
    readback = collection.get(include=["documents", "metadatas", "embeddings"])
    vectors = readback.get("embeddings")
    documents = readback.get("documents")
    metadatas = readback.get("metadatas")
    vectors = [] if vectors is None else vectors
    documents = [] if documents is None else documents
    metadatas = [] if metadatas is None else metadatas
    dimensions = {len(vector) for vector in vectors}
    required_metadata = ("heading_path", "course_id", "source_page", "book_page")
    if collection_metadata.get("hnsw:space") != "cosine":
        raise RuntimeError(f"candidate collection distance is {collection_metadata.get('hnsw:space')!r}")
    if len(vectors) != chunk_result.semantic_chunks or len(documents) != len(vectors) or len(metadatas) != len(vectors):
        raise RuntimeError("candidate readback count mismatch")
    if dimensions != {4096}:
        raise RuntimeError(f"candidate vector dimensions mismatch: {dimensions}")
    if any(
        any(key not in metadata or metadata[key] in (None, "", "[]") for key in required_metadata)
        for metadata in metadatas
    ):
        raise RuntimeError("candidate metadata provenance is incomplete")
    if ingest.error_count or ingest.success_count != status.document_count:
        raise RuntimeError(
            f"candidate ingest failed: success={ingest.success_count}, errors={ingest.error_count}, "
            f"collection_count={status.document_count}"
        )

    bundle_path = root / "chunks.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema_version": "course-candidate-chunks/1.0",
        "course_id": str(course.course_id),
        "resource_version": version,
        "source_sha256": source_sha256,
        "parser_mode": parser_mode,
        "embedding_model": model_name,
        "chunks": [
            _safe_json(asdict(chunk)) for chunk in chunk_result.chunks if chunk.metadata.chunk_type == "semantic"
        ],
    }
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "course-candidate-index/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "course_id": str(course.course_id),
        "resource_version": version,
        "status": "unready",
        "published": False,
        "revision": revision,
        "source": {"path": source.relative_to(PACKAGE_ROOT).as_posix(), "sha256": source_sha256},
        "parser": {"mode": parser_mode, "pages": parse_result.total_pages},
        "embedding": {"model": model_name, "distance": collection_metadata["hnsw:space"], "dimension": 4096},
        "collection_name": candidate_collection,
        "persist_directory": persist.relative_to(PACKAGE_ROOT).as_posix(),
        "candidate_bundle": bundle_path.relative_to(PACKAGE_ROOT).as_posix(),
        "chunk_count": chunk_result.semantic_chunks,
        "document_count": status.document_count,
        "build_seconds": round(time.perf_counter() - started, 3),
        "readback": {
            "collection_count": status.document_count,
            "vector_count": len(vectors),
            "vector_dimensions": sorted(dimensions),
            "source": parse_result.file_name,
            "collection_metadata": collection_metadata,
            "marker_provenance": parse_provenance,
        },
    }
    manifest_path = root / "candidate_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    vector_store = getattr(kb, "vector_store", None)
    close = getattr(vector_store, "_client", None)
    if close is not None and hasattr(close, "close"):
        close.close()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--parser-mode", choices=("marker",), default="marker")
    parser.add_argument("--persist-directory", type=Path)
    parser.add_argument("--collection-name")
    parser.add_argument("--embedding-model")
    parser.add_argument("--candidate-dir", help="isolated candidate directory under the version root")
    parser.add_argument("--marker-intermediate", type=Path, help="saved local Marker JSON parse result")
    parser.add_argument("--no-cache", action="store_true", help="reserved for parity with the shared builder")
    args = parser.parse_args(argv)
    print(json.dumps(build_candidate(**vars(args)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
