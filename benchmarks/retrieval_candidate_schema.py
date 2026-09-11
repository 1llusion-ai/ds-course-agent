"""Typed contracts for isolated retrieval chunk candidates and indexes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from benchmarks.retrieval_gold_schema import Artifact, Digest, GoldModel, PageNumber, Text, unique

CandidateId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class ChunkCandidateSpec(GoldModel):
    """One controlled semantic chunking configuration."""

    id: CandidateId
    chunk_size: Annotated[int, Field(ge=200)]
    chunk_overlap: Annotated[int, Field(ge=0)]
    max_chunk_size: Annotated[int, Field(ge=200)]

    @model_validator(mode="after")
    def size_order(self) -> ChunkCandidateSpec:
        """Reject overlap-dominated and contradictory chunk parameters."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.max_chunk_size < self.chunk_size:
            raise ValueError("max_chunk_size must be at least chunk_size")
        return self


class ChunkCandidateMatrix(GoldModel):
    """Frozen small candidate matrix used before embedding comparisons."""

    schema_version: Literal["retrieval-chunk-candidates/1.0"]
    candidates: Annotated[list[ChunkCandidateSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_candidates(self) -> ChunkCandidateMatrix:
        """Prevent two configurations from sharing an experiment identity."""
        unique([candidate.id for candidate in self.candidates], "candidate")
        unique(
            [
                (candidate.chunk_size, candidate.chunk_overlap, candidate.max_chunk_size)
                for candidate in self.candidates
            ],
            "candidate parameters",
        )
        return self


class CandidateChunk(GoldModel):
    """One semantic chunk mapped back to a frozen single-page source interval."""

    id: Text
    content: Text
    content_sha256: Digest
    source_id: Text
    source_page: PageNumber
    book_page: Annotated[int, Field(ge=1, le=240)]
    source_start: Annotated[int, Field(ge=0)]
    source_end: Annotated[int, Field(gt=0)]
    mapping_method: Literal["remove_whitespace_v1"]
    chapter: str
    chapter_number: str
    section: str
    section_number: str
    subsection: str
    subsection_number: str

    @model_validator(mode="after")
    def source_interval(self) -> CandidateChunk:
        """Reject empty mapped source envelopes."""
        if self.source_end <= self.source_start:
            raise ValueError("source_end must exceed source_start")
        return self


class CandidateDiagnostics(GoldModel):
    """Build-time structural checks independent of an embedding model."""

    body_page_count: Annotated[int, Field(ge=1)]
    semantic_chunk_count: Annotated[int, Field(ge=1)]
    average_chunk_characters: Annotated[float, Field(gt=0.0)]
    maximum_chunk_characters: Annotated[int, Field(gt=0)]
    ambiguous_mapping_count: Annotated[int, Field(ge=0)]
    atomic_unit_count: Annotated[int, Field(ge=0)]
    intact_atomic_unit_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def atomic_count_order(self) -> CandidateDiagnostics:
        """Keep atomic-unit integrity counts coherent."""
        if self.intact_atomic_unit_count > self.atomic_unit_count:
            raise ValueError("intact atomic units exceed total atomic units")
        return self


class CandidateChunkBundle(GoldModel):
    """Hash-bound chunk output generated from the frozen source baseline."""

    schema_version: Literal["retrieval-candidate-chunks/1.0"]
    created_at: AwareDatetime
    source_manifest: Artifact
    source_manifest_canonical_sha256: Digest
    chunker: Artifact
    candidate: ChunkCandidateSpec
    diagnostics: CandidateDiagnostics
    chunks: Annotated[list[CandidateChunk], Field(min_length=1)]

    @model_validator(mode="after")
    def chunk_integrity(self) -> CandidateChunkBundle:
        """Reject duplicate chunk identities and stale count summaries."""
        unique([chunk.id for chunk in self.chunks], "candidate chunk")
        if self.diagnostics.semantic_chunk_count != len(self.chunks):
            raise ValueError("semantic chunk count is stale")
        return self


class EmbeddingIndexSpec(GoldModel):
    """Embedding and vector-index settings for one isolated candidate index."""

    id: CandidateId
    model: Text
    dimensions: Annotated[int, Field(gt=0)] | None
    distance: Literal["cosine"]
    query_prefix: str
    batch_size: Annotated[int, Field(ge=1, le=128)]


class EmbeddingIndexMatrix(GoldModel):
    """Frozen embedding variants available to the staged experiment."""

    schema_version: Literal["retrieval-embedding-candidates/1.0"]
    embeddings: Annotated[list[EmbeddingIndexSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_embeddings(self) -> EmbeddingIndexMatrix:
        """Reject duplicate experiment names and equivalent model settings."""
        unique([embedding.id for embedding in self.embeddings], "embedding candidate")
        unique(
            [
                (embedding.model, embedding.dimensions, embedding.distance, embedding.query_prefix)
                for embedding in self.embeddings
            ],
            "embedding settings",
        )
        return self


class CandidateIndexManifest(GoldModel):
    """Provenance and operational result of one isolated Chroma build."""

    schema_version: Literal["retrieval-candidate-index/1.0"]
    created_at: AwareDatetime
    candidate_bundle: Artifact
    embedding: EmbeddingIndexSpec
    persist_directory: Text
    collection_name: Text
    document_count: Annotated[int, Field(ge=1)]
    vector_dimension: Annotated[int, Field(gt=0)]
    build_seconds: Annotated[float, Field(ge=0.0)]
