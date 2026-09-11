"""Strict, chunk-independent contracts for offline retrieval evidence labels."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PageNumber = Annotated[int, Field(ge=1, le=248)]
Split = Literal["dev", "test"]


class GoldModel(BaseModel):
    """Reject coercion and undeclared fields at every nesting level."""

    model_config = ConfigDict(extra="forbid", strict=True)


def canonical_sha256(value: BaseModel | dict) -> str:
    """Hash sorted, compact UTF-8 JSON without ASCII escaping."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def unique(values: list, label: str) -> None:
    """Reject duplicate identities instead of silently deduplicating annotations."""
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class Artifact(GoldModel):
    """A file pinned by content, with a root-relative portable path."""

    path: Text
    sha256: Digest

    @model_validator(mode="after")
    def relative_path(self) -> Artifact:
        """Disallow traversal and platform-specific absolute paths."""
        if "\\" in self.path or ":" in self.path or any(p in ("", ".", "..") for p in self.path.split("/")):
            raise ValueError("artifact path must be a normalized relative POSIX path")
        return self


class SourceManifest(GoldModel):
    """One reviewed textbook baseline; caches are hashed, never unpickled here."""

    source_id: Text
    pdf: Artifact
    parse_cache: Artifact
    clean_cache: Artifact
    pages_export: Artifact
    atomic_units: Artifact
    total_pages: Literal[248]
    book_page_offset: Literal[-8]
    parser_mode: Text
    cleaner_version: Text
    exporter_version: Text
    git_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    working_tree_dirty: bool
    code_files: list[Artifact]

    @model_validator(mode="after")
    def code_provenance(self) -> SourceManifest:
        """A dirty revision needs actual file fingerprints."""
        if self.working_tree_dirty and not self.code_files:
            raise ValueError("dirty source requires code_files")
        unique([item.path for item in self.code_files], "code file")
        return self


class SourcePage(GoldModel):
    """Unmodified clean text; offsets count Unicode code points."""

    source_id: Text
    source_page: PageNumber
    book_page: Annotated[int, Field(ge=1, le=240)] | None
    text: str
    text_sha256: Digest
    role: Literal["body", "front_matter", "non_body"]


class Segment(GoldModel):
    """An exact, half-open, single-page evidence span."""

    source_id: Text
    source_page: PageNumber
    book_page: Annotated[int, Field(ge=1, le=240)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: Text
    section_path: list[Text]

    @model_validator(mode="after")
    def interval(self) -> Segment:
        """Catch reversed and empty spans before consulting source text."""
        if self.end <= self.start:
            raise ValueError("segment end must exceed start")
        return self


class AtomicUnit(GoldModel):
    """A reviewed formula, table, or code unit that must remain complete."""

    id: Text
    kind: Literal["formula", "table", "code"]
    segments: Annotated[list[Segment], Field(min_length=1)]


class EvidenceRegion(GoldModel):
    """All segments within a region are jointly required."""

    id: Text
    relevance: Annotated[int, Field(ge=0, le=3)]
    rationale: Text
    segments: Annotated[list[Segment], Field(min_length=1)]
    required_atomic_unit_ids: list[Text]


class AnswerRequirement(GoldModel):
    """One minimum answer point, used only by annotation and evaluation."""

    id: Text
    statement: Text


class RequirementCoverage(GoldModel):
    """Evidence supporting an answer point within one sufficient alternative."""

    requirement_id: Text
    region_ids: Annotated[list[Text], Field(min_length=1)]


class SufficientSet(GoldModel):
    """AND of region IDs; the outer list of these sets means OR."""

    id: Text
    region_ids: Annotated[list[Text], Field(min_length=1)]
    coverage: Annotated[list[RequirementCoverage], Field(min_length=1)]


class ScopeCheck(GoldModel):
    """Source-search audit for ambiguity or absence of a supported answer."""

    source_pages: Annotated[list[PageNumber], Field(min_length=1)]
    section_paths: list[list[Text]]
    terms_checked: Annotated[list[Text], Field(min_length=1)]
    rationale: Text


class Annotation(GoldModel):
    """Reference to one independently generated agent annotation batch."""

    annotator_id: Text
    model: Text
    reasoning_effort: Text
    submitted_at: AwareDatetime
    artifact: Artifact


class Decision(GoldModel):
    """Coordinator decision bound to current sample and source hashes."""

    coordinator_id: Text
    decided_at: AwareDatetime
    resolution: Literal["consensus", "merged", "reject"]
    notes: Text


class Review(GoldModel):
    """Version-bound dual-agent audit trail."""

    status: Literal["draft", "double_annotated", "disputed", "accepted", "rejected"]
    sample_content_sha256: Digest | None
    source_manifest_sha256: Digest | None
    annotations: list[Annotation]
    decision: Decision | None


class Sample(GoldModel):
    """One information need, independent of any candidate index."""

    id: Text
    family_id: Text
    split: Split
    query: Text
    question_type: Literal[
        "definition",
        "explanation",
        "comparison",
        "procedure",
        "code_api",
        "table_interpretation",
        "formula_interpretation",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    concepts: Annotated[list[Text], Field(min_length=1)]
    language_features: list[Literal["natural", "alias", "abbreviation", "underspecified", "misconception"]]
    answerability: Literal["answerable", "needs_clarification", "not_in_source"]
    intent_note: Text
    answer_requirements: list[AnswerRequirement]
    evidence_regions: list[EvidenceRegion]
    sufficient_sets: list[SufficientSet]
    scope_check: ScopeCheck | None
    review: Review

    @model_validator(mode="after")
    def evidence_graph(self) -> Sample:
        """Require complete, non-orphaned AND/OR evidence references."""
        unique([r.id for r in self.answer_requirements], "requirement")
        unique([r.id for r in self.evidence_regions], "region")
        unique([s.id for s in self.sufficient_sets], "sufficient set")
        unique(self.concepts, "concept")
        unique(self.language_features, "language feature")
        if self.answerability == "answerable":
            if not self.answer_requirements or not self.sufficient_sets or self.scope_check is not None:
                raise ValueError("answerable samples require requirements/sets and no scope_check")
        elif self.answer_requirements or self.sufficient_sets or self.scope_check is None:
            raise ValueError("non-answerable samples require scope_check and empty requirements/sets")
        requirements = {r.id for r in self.answer_requirements}
        necessary = {r.id for r in self.evidence_regions if r.relevance == 3}
        consumed: set[str] = set()
        alternatives: list[tuple[str, ...]] = []
        for sufficient in self.sufficient_sets:
            unique(sufficient.region_ids, "set region")
            regions = set(sufficient.region_ids)
            if not regions <= necessary:
                raise ValueError("sufficient sets must reference relevance=3 regions")
            unique([c.requirement_id for c in sufficient.coverage], "coverage requirement")
            if {c.requirement_id for c in sufficient.coverage} != requirements:
                raise ValueError("every sufficient set must cover all requirements")
            used: set[str] = set()
            for coverage in sufficient.coverage:
                unique(coverage.region_ids, "coverage region")
                if not set(coverage.region_ids) <= regions:
                    raise ValueError("coverage references region outside its sufficient set")
                used.update(coverage.region_ids)
            if used != regions:
                raise ValueError("sufficient set contains unused regions")
            consumed.update(regions)
            alternatives.append(tuple(sorted(regions)))
        unique(alternatives, "alternative")
        if consumed != necessary:
            raise ValueError("orphaned relevance=3 evidence")
        for region in self.evidence_regions:
            unique(region.required_atomic_unit_ids, "atomic unit reference")
        return self


class QuerySeed(GoldModel):
    """Frozen query metadata shared by independent annotators."""

    id: Text
    family_id: Text
    split: Split
    query: Text
    question_type: Literal[
        "definition",
        "explanation",
        "comparison",
        "procedure",
        "code_api",
        "table_interpretation",
        "formula_interpretation",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    concepts: Annotated[list[Text], Field(min_length=1)]
    language_features: list[Literal["natural", "alias", "abbreviation", "underspecified", "misconception"]]


class QuerySeedDataset(GoldModel):
    """Query families frozen before candidate chunk tuning."""

    schema_version: Literal["retrieval-query-seed/1.0"]
    dataset_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    split_policy: Text
    queries: Annotated[list[QuerySeed], Field(min_length=1)]

    @model_validator(mode="after")
    def query_integrity(self) -> QuerySeedDataset:
        unique([query.id for query in self.queries], "query")
        families: dict[str, str] = {}
        for query in self.queries:
            previous = families.setdefault(query.family_id, query.split)
            if previous != query.split:
                raise ValueError("query family leaks across dev/test")
        return self


class AgentAnnotationBatch(GoldModel):
    """One model's independent labels for a frozen query set and source."""

    schema_version: Literal["retrieval-agent-annotation/1.0"]
    annotator_id: Text
    model: Text
    reasoning_effort: Text
    submitted_at: AwareDatetime
    source_manifest_path: Text
    source_manifest_sha256: Digest
    samples: Annotated[list[Sample], Field(min_length=1)]

    @model_validator(mode="after")
    def annotation_integrity(self) -> AgentAnnotationBatch:
        unique([sample.id for sample in self.samples], "annotated sample")
        return self


class SplitAssignments(GoldModel):
    """Frozen membership, also stored as a separately hashed JSON artifact."""

    dev: list[Text]
    test: list[Text]


class SplitManifest(GoldModel):
    """Reproducible family-level split policy and its concrete assignments."""

    grouping_version: Text
    seed: Annotated[int, Field(ge=0)]
    frozen_at: AwareDatetime
    assignments: SplitAssignments
    artifact: Artifact


class GoldDataset(GoldModel):
    """Versioned labels for the reviewed 248-page course textbook."""

    schema_version: Literal["retrieval-evidence/1.0"]
    dataset_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    source_manifest: SourceManifest
    split_manifest: SplitManifest
    samples: Annotated[list[Sample], Field(min_length=1)]

    @model_validator(mode="after")
    def split_integrity(self) -> GoldDataset:
        """Reject duplicate IDs, membership drift, and family leakage."""
        unique([s.id for s in self.samples], "sample")
        assignments = self.split_manifest.assignments
        unique(assignments.dev + assignments.test, "split membership")
        families: dict[str, str] = {}
        for split in ("dev", "test"):
            if set(getattr(assignments, split)) != {s.id for s in self.samples if s.split == split}:
                raise ValueError("split manifest does not match samples")
        for sample in self.samples:
            previous = families.setdefault(sample.family_id, sample.split)
            if previous != sample.split:
                raise ValueError("family leaks across dev/test")
        return self


def sample_content_sha256(sample: Sample) -> str:
    """Bind a review to all sample fields except the review itself."""
    return canonical_sha256(sample.model_dump(mode="json", exclude={"review"}))


def dataset_json_schema() -> dict:
    """Generate the portable structural schema; semantic checks remain mandatory."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **GoldDataset.model_json_schema()}
