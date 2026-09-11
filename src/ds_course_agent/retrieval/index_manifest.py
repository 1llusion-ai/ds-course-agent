"""Typed manifest for a promoted production retrieval index."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = ["IndexArtifact", "PromotedIndexManifest"]
