"""Typed manifest for a promoted production retrieval index."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.shared.readiness import ReadinessCheck

if TYPE_CHECKING:
    from ds_course_agent.shared.config.schema import Settings


class IndexArtifact(BaseModel):
    """One hash-bound repository or runtime artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PromotedIndexManifest(BaseModel):
    """Identity and verification record for one production-shaped index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^retrieval-production-index/1\.0$")
    created_at: datetime
    candidate_bundle: IndexArtifact
    candidate_index_manifest: IndexArtifact
    source_collection: str = Field(min_length=1)
    destination_collection: str = Field(min_length=1)
    persist_directory: str = Field(min_length=1)
    document_count: int = Field(gt=0)
    vector_dimension: int = Field(gt=0)
    embedding_model: str = Field(min_length=1)
    embedding_distance: str = Field(pattern=r"^cosine$")
    embedding_query_prefix: str
    metadata_schema_version: str = Field(pattern=r"^retrieval-provenance/1\.0$")
    collection_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_vectors_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_vectors_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    maximum_vector_absolute_error: float = Field(ge=0.0, le=1e-7)
    minimum_vector_cosine_similarity: float = Field(ge=0.999999, le=1.000001)
    code_revision: str = Field(min_length=1)
    build_seconds: float = Field(ge=0.0)


def resolve_manifest_path(settings: Settings) -> Path:
    """Resolve the configured production manifest without touching the index."""

    configured = str(settings.RAG_INDEX_MANIFEST_PATH or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path

    persist = Path(settings.CHROMA_PERSIST_DIR).resolve()
    return (
        persist.parent / "production_manifest.json"
        if persist.name == "chroma"
        else persist / "production_manifest.json"
    )


def load_and_validate_manifest(settings: Settings) -> PromotedIndexManifest:
    """Load a manifest and validate the configuration-bound identity fields."""

    path = resolve_manifest_path(settings)
    if not path.is_file():
        raise RuntimeError(f"production retrieval index manifest is missing: {path}")
    manifest = PromotedIndexManifest.model_validate_json(path.read_bytes())
    expected_persist = (PROJECT_ROOT / manifest.persist_directory).resolve()
    if expected_persist != Path(settings.CHROMA_PERSIST_DIR).resolve():
        raise RuntimeError("production retrieval manifest persist directory does not match configuration")
    if manifest.destination_collection != settings.COLLECTION_NAME:
        raise RuntimeError("production retrieval manifest collection does not match configuration")
    if manifest.embedding_model != settings.EMBEDDING_MODEL:
        raise RuntimeError("query embedding model does not match the production retrieval index")
    if manifest.embedding_distance != "cosine" or manifest.embedding_query_prefix:
        raise RuntimeError("production retrieval index must use cosine distance and an empty query prefix")
    return manifest


def check_production_index_readiness(settings: Settings) -> ReadinessCheck:
    """Verify manifest and Chroma collection identity using read-only operations."""

    try:
        manifest = load_and_validate_manifest(settings)
        persist_dir = Path(settings.CHROMA_PERSIST_DIR)
        if not persist_dir.is_dir():
            return ReadinessCheck("retrieval_index", False, "configured Chroma persist directory is missing")

        import chromadb

        client = chromadb.PersistentClient(path=str(persist_dir))
        try:
            collection = client.get_collection(settings.COLLECTION_NAME)
            actual_count = collection.count()
            if actual_count != manifest.document_count:
                return ReadinessCheck(
                    "retrieval_index",
                    False,
                    f"collection document count {actual_count} does not match manifest {manifest.document_count}",
                )
            payload = collection.get(include=["metadatas"], limit=1)
            metadatas = payload.get("metadatas") or []
            if not metadatas or (metadatas[0] or {}).get("collection_revision") != manifest.collection_revision:
                return ReadinessCheck(
                    "retrieval_index",
                    False,
                    "collection revision does not match the production manifest",
                )
        finally:
            client.close()
        return ReadinessCheck(
            "retrieval_index",
            True,
            f"{manifest.destination_collection} ready with {manifest.document_count} documents",
        )
    except Exception as exc:
        return ReadinessCheck("retrieval_index", False, str(exc))


__all__ = [
    "IndexArtifact",
    "PromotedIndexManifest",
    "check_production_index_readiness",
    "load_and_validate_manifest",
    "resolve_manifest_path",
]
