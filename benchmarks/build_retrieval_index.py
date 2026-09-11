"""Build one isolated Chroma index for a frozen chunk and embedding candidate."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import chromadb
from langchain_openai import OpenAIEmbeddings

import ds_course_agent.shared.config as config
from benchmarks.retrieval_candidate_schema import (
    CandidateChunkBundle,
    CandidateIndexManifest,
    EmbeddingIndexMatrix,
    EmbeddingIndexSpec,
)


def _artifact(root: Path, path: Path) -> dict[str, str]:
    content = path.read_bytes()
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def create_embedding_client(spec: EmbeddingIndexSpec) -> OpenAIEmbeddings:
    """Create an explicit experiment client without mutating process configuration."""
    kwargs = {
        "model": spec.model,
        "api_key": config.API_KEY,
        "base_url": config.BASE_URL,
        "tiktoken_enabled": False,
        "check_embedding_ctx_length": False,
        "timeout": max(20.0, float(config.EMBEDDING_TIMEOUT_SECONDS)),
        "max_retries": 2,
        "chunk_size": spec.batch_size,
    }
    if spec.dimensions is not None:
        kwargs["dimensions"] = spec.dimensions
    return OpenAIEmbeddings(**kwargs)


def build_index(
    *,
    root: Path,
    bundle_path: Path,
    output: Path,
    embedding: EmbeddingIndexSpec,
) -> CandidateIndexManifest:
    """Embed and index one candidate using an atomic fresh-directory publish."""
    root = root.resolve()
    bundle_path = bundle_path.resolve()
    output = output.resolve()
    candidate_root = root / "var" / "chroma_candidates"
    active_root = root / "var" / "chroma_db"
    if not output.is_relative_to(candidate_root) or output.is_relative_to(active_root):
        raise ValueError("index output must be under var/chroma_candidates and outside var/chroma_db")
    if output.exists():
        raise ValueError("index output already exists; refusing overwrite")
    bundle = CandidateChunkBundle.model_validate_json(bundle_path.read_bytes())
    if hashlib.sha256((root / bundle.chunker.path).read_bytes()).hexdigest() != bundle.chunker.sha256:
        raise ValueError("candidate chunker hash is stale")
    if not config.API_KEY:
        raise ValueError("EMBEDDING_API_KEY is required")

    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f".{embedding.id}-", dir=output.parent) as temporary:
        temporary_root = Path(temporary)
        persist = temporary_root / "chroma"
        collection_name = f"retrieval_{bundle.candidate.id}_{embedding.id}"
        client = chromadb.PersistentClient(path=str(persist))
        collection = client.create_collection(collection_name, metadata={"hnsw:space": embedding.distance})
        model = create_embedding_client(embedding)
        chunks = bundle.chunks
        vector_dimension = 0
        for offset in range(0, len(chunks), embedding.batch_size):
            batch = chunks[offset : offset + embedding.batch_size]
            vectors = model.embed_documents([chunk.content for chunk in batch])
            if len(vectors) != len(batch):
                raise ValueError("embedding API returned an unexpected vector count")
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1:
                raise ValueError("embedding API returned inconsistent dimensions")
            batch_dimension = dimensions.pop()
            if vector_dimension and vector_dimension != batch_dimension:
                raise ValueError("embedding dimension changed between batches")
            vector_dimension = batch_dimension
            collection.add(
                ids=[chunk.id for chunk in batch],
                documents=[chunk.content for chunk in batch],
                embeddings=vectors,
                metadatas=[
                    {
                        "source_id": chunk.source_id,
                        "source_page": chunk.source_page,
                        "book_page": chunk.book_page,
                        "source_start": chunk.source_start,
                        "source_end": chunk.source_end,
                        "chapter": chunk.chapter,
                        "section": chunk.section,
                    }
                    for chunk in batch
                ],
            )
            print(f"embedded {min(offset + len(batch), len(chunks))}/{len(chunks)}", flush=True)
        document_count = collection.count()
        if document_count != len(chunks):
            raise ValueError("Chroma document count differs from candidate bundle")
        manifest = CandidateIndexManifest(
            schema_version="retrieval-candidate-index/1.0",
            created_at=datetime.now().astimezone(),
            candidate_bundle=_artifact(root, bundle_path),
            embedding=embedding,
            persist_directory=(output / "chroma").relative_to(root).as_posix(),
            collection_name=collection_name,
            document_count=document_count,
            vector_dimension=vector_dimension,
            build_seconds=time.perf_counter() - started,
        )
        (temporary_root / "index_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        del collection, client, model
        gc.collect()
        os.replace(temporary_root, output)
    return manifest


def main() -> int:
    """Resolve one named embedding spec and build a fresh isolated index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--embedding-matrix", type=Path, required=True)
    parser.add_argument("--embedding-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    matrix = EmbeddingIndexMatrix.model_validate_json(args.embedding_matrix.read_bytes())
    matches = [embedding for embedding in matrix.embeddings if embedding.id == args.embedding_id]
    if len(matches) != 1:
        raise ValueError(f"unknown embedding candidate: {args.embedding_id}")
    manifest = build_index(
        root=args.root,
        bundle_path=args.bundle,
        output=args.output,
        embedding=matches[0],
    )
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
