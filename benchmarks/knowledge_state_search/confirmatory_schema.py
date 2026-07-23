"""Typed loader and integrity checks for the v3 confirmatory benchmark."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.evidence import SnapshotSource

_DATA_FILES = (
    "tasks.jsonl",
    "profiles.jsonl",
    "claims.jsonl",
    "claim_edges.jsonl",
    "sources.jsonl",
    "evidence_annotations.jsonl",
    "splits.json",
    "annotation_audit.json",
)


class ClaimKind(str, Enum):
    """Canonical teaching claim categories."""

    CORE = "core"
    PREREQUISITE = "prerequisite"
    MISCONCEPTION = "misconception"
    GOAL = "goal"


class EdgeType(str, Enum):
    """Allowed directed relations in a claim graph."""

    PREREQUISITE = "prerequisite"
    CAUSAL = "causal"
    EXPLAINS = "explains"
    QUALIFIES = "qualifies"
    CONTRASTS = "contrasts"
    EXAMPLE_OF = "example_of"


class ProfileField(str, Enum):
    """Typed learner-profile fields that may activate a learner claim."""

    MASTERED_CONCEPT = "mastered_concept"
    WEAK_CONCEPT = "weak_concept"
    MISCONCEPTION = "misconception"
    LEARNING_GOAL = "learning_goal"


class TargetType(str, Enum):
    """Evidence annotation target types."""

    CLAIM = "claim"
    EDGE = "edge"


class EvidenceRelation(str, Enum):
    """Exhaustive relation labels for candidate evidence pairs."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    CONTRADICTED = "contradicted"
    DISTRACTOR = "distractor"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class RecordCounts:
    """Expected record counts recorded in the manifest."""

    tasks: int
    profiles: int
    claims: int
    edges: int
    sources: int
    annotations: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecordCounts:
        """Build typed manifest counts."""

        return cls(
            tasks=_non_negative_int(payload, "tasks"),
            profiles=_non_negative_int(payload, "profiles"),
            claims=_non_negative_int(payload, "claims"),
            edges=_non_negative_int(payload, "edges"),
            sources=_non_negative_int(payload, "sources"),
            annotations=_non_negative_int(payload, "annotations"),
        )


@dataclass(frozen=True)
class FileFingerprint:
    """SHA-256 fingerprint for one immutable benchmark file."""

    path: str
    sha256: str

    @classmethod
    def from_pair(cls, path: str, sha256: Any) -> FileFingerprint:
        """Build and validate one file fingerprint."""

        if path not in _DATA_FILES:
            raise ValueError(f"manifest contains unsupported fingerprint path: {path}")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ValueError(f"invalid SHA-256 fingerprint for: {path}")
        try:
            int(sha256, 16)
        except ValueError as exc:
            raise ValueError(f"invalid SHA-256 fingerprint for: {path}") from exc
        return cls(path=path, sha256=sha256)


@dataclass(frozen=True)
class ConfirmatoryManifest:
    """Version, task scope, counts, and immutable file fingerprints."""

    benchmark_id: str
    schema_version: int
    created_at: str
    source_capture_method: str
    provenance_note: str
    task_ids: tuple[str, ...]
    counts: RecordCounts
    fingerprints: tuple[FileFingerprint, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConfirmatoryManifest:
        """Build a typed v3 manifest."""

        raw_fingerprints = payload.get("file_sha256")
        if not isinstance(raw_fingerprints, dict):
            raise ValueError("manifest.file_sha256 must be an object")
        task_ids = _string_tuple(payload, "task_ids")
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("manifest.task_ids must be unique")
        return cls(
            benchmark_id=_required_string(payload, "benchmark_id"),
            schema_version=_non_negative_int(payload, "schema_version"),
            created_at=_required_string(payload, "created_at"),
            source_capture_method=_required_string(payload, "source_capture_method"),
            provenance_note=_required_string(payload, "provenance_note"),
            task_ids=task_ids,
            counts=RecordCounts.from_dict(_required_object(payload, "counts")),
            fingerprints=tuple(
                FileFingerprint.from_pair(path, sha256) for path, sha256 in sorted(raw_fingerprints.items())
            ),
        )


@dataclass(frozen=True)
class ConfirmatoryTask:
    """One frozen teaching question independent of any learner profile."""

    task_id: str
    question: str
    target_concepts: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConfirmatoryTask:
        """Build a typed confirmatory task."""

        return cls(
            task_id=_required_string(payload, "task_id"),
            question=_required_string(payload, "question"),
            target_concepts=_non_empty_string_tuple(payload, "target_concepts"),
        )


@dataclass(frozen=True)
class LearnerProfile:
    """De-identified learner state used to activate learner-specific claims."""

    task_id: str
    profile_id: str
    level: str
    mastered_concepts: tuple[str, ...]
    weak_concepts: tuple[str, ...]
    misconceptions: tuple[str, ...]
    learning_goal: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LearnerProfile:
        """Build a typed learner profile."""

        return cls(
            task_id=_required_string(payload, "task_id"),
            profile_id=_required_string(payload, "profile_id"),
            level=_required_string(payload, "level"),
            mastered_concepts=_string_tuple(payload, "mastered_concepts"),
            weak_concepts=_string_tuple(payload, "weak_concepts"),
            misconceptions=_string_tuple(payload, "misconceptions"),
            learning_goal=_required_string(payload, "learning_goal"),
        )


@dataclass(frozen=True)
class ProfileCondition:
    """Profile trigger that makes a learner claim applicable."""

    field: ProfileField
    value: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProfileCondition:
        """Build a typed learner-claim trigger."""

        return cls(
            field=ProfileField(_required_string(payload, "field")),
            value=_required_string(payload, "value"),
        )

    def matches(self, profile: LearnerProfile) -> bool:
        """Return whether this trigger is present in a learner profile."""

        if self.field is ProfileField.MASTERED_CONCEPT:
            return self.value in profile.mastered_concepts
        if self.field is ProfileField.WEAK_CONCEPT:
            return self.value in profile.weak_concepts
        if self.field is ProfileField.MISCONCEPTION:
            return self.value in profile.misconceptions
        return self.value == profile.learning_goal


@dataclass(frozen=True)
class CanonicalClaim:
    """A gold teaching claim independent of any planner output."""

    task_id: str
    claim_id: str
    kind: ClaimKind
    concept: str
    description: str
    hard: bool
    priority: int
    oracle_query: str
    profile_condition: ProfileCondition | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CanonicalClaim:
        """Build a canonical claim and its optional profile condition."""

        raw_condition = payload.get("profile_condition")
        if raw_condition is not None and not isinstance(raw_condition, dict):
            raise ValueError("profile_condition must be an object or null")
        return cls(
            task_id=_required_string(payload, "task_id"),
            claim_id=_required_string(payload, "claim_id"),
            kind=ClaimKind(_required_string(payload, "kind")),
            concept=_required_string(payload, "concept"),
            description=_required_string(payload, "description"),
            hard=_required_bool(payload, "hard"),
            priority=_positive_int(payload, "priority"),
            oracle_query=_required_string(payload, "oracle_query"),
            profile_condition=(ProfileCondition.from_dict(raw_condition) if raw_condition is not None else None),
        )


@dataclass(frozen=True)
class ClaimEdge:
    """A directed relation between two canonical claims."""

    task_id: str
    edge_id: str
    from_claim_id: str
    to_claim_id: str
    edge_type: EdgeType
    required: bool
    path_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClaimEdge:
        """Build a typed claim edge."""

        return cls(
            task_id=_required_string(payload, "task_id"),
            edge_id=_required_string(payload, "edge_id"),
            from_claim_id=_required_string(payload, "from_claim_id"),
            to_claim_id=_required_string(payload, "to_claim_id"),
            edge_type=EdgeType(_required_string(payload, "edge_type")),
            required=_required_bool(payload, "required"),
            path_ids=_string_tuple(payload, "path_ids"),
        )


@dataclass(frozen=True)
class EvidenceAnnotation:
    """A blinded relation between a source and a canonical target."""

    task_id: str
    target_type: TargetType
    target_id: str
    source_id: str
    relation: EvidenceRelation

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceAnnotation:
        """Build one explicit target/source relation."""

        return cls(
            task_id=_required_string(payload, "task_id"),
            target_type=TargetType(_required_string(payload, "target_type")),
            target_id=_required_string(payload, "target_id"),
            source_id=_required_string(payload, "source_id"),
            relation=EvidenceRelation(_required_string(payload, "relation")),
        )


@dataclass(frozen=True)
class BenchmarkSplit:
    """Named task partition used by the benchmark."""

    name: str
    task_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnnotationAudit:
    """Recorded annotation-review state without overstating pilot maturity."""

    status: str
    annotators: tuple[str, ...]
    adjudicated: bool
    independently_judged_pairs: int
    notes: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnnotationAudit:
        """Build annotation-audit metadata."""

        return cls(
            status=_required_string(payload, "status"),
            annotators=_non_empty_string_tuple(payload, "annotators"),
            adjudicated=_required_bool(payload, "adjudicated"),
            independently_judged_pairs=_non_negative_int(
                payload,
                "independently_judged_pairs",
            ),
            notes=_required_string(payload, "notes"),
        )


@dataclass(frozen=True)
class ConfirmatorySchema:
    """Complete typed graph/evidence contract for one confirmatory dataset."""

    manifest: ConfirmatoryManifest
    tasks: tuple[ConfirmatoryTask, ...]
    profiles: tuple[LearnerProfile, ...]
    claims: tuple[CanonicalClaim, ...]
    edges: tuple[ClaimEdge, ...]
    sources: tuple[SnapshotSource, ...]
    annotations: tuple[EvidenceAnnotation, ...]
    splits: tuple[BenchmarkSplit, ...]
    annotation_audit: AnnotationAudit

    @classmethod
    def load(cls, directory: str | Path) -> ConfirmatorySchema:
        """Load, fingerprint-check, and validate a v3 benchmark directory."""

        root = Path(directory)
        manifest = ConfirmatoryManifest.from_dict(json.loads((root / "manifest.json").read_text(encoding="utf-8")))
        _validate_file_fingerprints(root, manifest)
        schema = cls(
            manifest=manifest,
            tasks=tuple(ConfirmatoryTask.from_dict(item) for item in _read_jsonl(root / "tasks.jsonl")),
            profiles=tuple(LearnerProfile.from_dict(item) for item in _read_jsonl(root / "profiles.jsonl")),
            claims=tuple(CanonicalClaim.from_dict(item) for item in _read_jsonl(root / "claims.jsonl")),
            edges=tuple(ClaimEdge.from_dict(item) for item in _read_jsonl(root / "claim_edges.jsonl")),
            sources=tuple(SnapshotSource.from_dict(item) for item in _read_jsonl(root / "sources.jsonl")),
            annotations=tuple(
                EvidenceAnnotation.from_dict(item) for item in _read_jsonl(root / "evidence_annotations.jsonl")
            ),
            splits=_load_splits(root / "splits.json"),
            annotation_audit=AnnotationAudit.from_dict(
                json.loads((root / "annotation_audit.json").read_text(encoding="utf-8"))
            ),
        )
        schema.validate()
        return schema

    def validate(self) -> None:
        """Raise ValueError when graph, profile, source, or annotation invariants fail."""

        from benchmarks.knowledge_state_search.confirmatory_validation import (
            validate_schema,
        )

        validate_schema(self)

    def validate_pilot_contract(self) -> None:
        """Enforce the stricter three-task Phase A discriminability contract."""

        from benchmarks.knowledge_state_search.confirmatory_validation import (
            validate_pilot_contract,
        )

        validate_pilot_contract(self)

    def validate_phase_b_contract(self) -> None:
        """Enforce the frozen twelve-task Phase B dataset contract."""

        from benchmarks.knowledge_state_search.confirmatory_validation import (
            validate_phase_b_contract,
        )

        validate_phase_b_contract(self)

    def profiles_for_task(self, task_id: str) -> tuple[LearnerProfile, ...]:
        """Return profiles belonging to one task."""

        return tuple(profile for profile in self.profiles if profile.task_id == task_id)

    def claims_for_task(self, task_id: str) -> tuple[CanonicalClaim, ...]:
        """Return canonical claims belonging to one task."""

        return tuple(claim for claim in self.claims if claim.task_id == task_id)

    def edges_for_task(self, task_id: str) -> tuple[ClaimEdge, ...]:
        """Return claim edges belonging to one task."""

        return tuple(edge for edge in self.edges if edge.task_id == task_id)

    def sources_for_task(self, task_id: str) -> tuple[SnapshotSource, ...]:
        """Return source excerpts belonging to one task."""

        return tuple(source for source in self.sources if source.task_id == task_id)

    def annotations_for_task(self, task_id: str) -> tuple[EvidenceAnnotation, ...]:
        """Return explicit target/source relations belonging to one task."""

        return tuple(annotation for annotation in self.annotations if annotation.task_id == task_id)

    def core_claims(self, task_id: str) -> tuple[CanonicalClaim, ...]:
        """Return the shared core contract for one task."""

        return tuple(claim for claim in self.claims_for_task(task_id) if claim.kind is ClaimKind.CORE)

    def active_learner_claims(
        self,
        profile: LearnerProfile,
    ) -> tuple[CanonicalClaim, ...]:
        """Return learner claims activated by one de-identified profile."""

        return tuple(
            claim
            for claim in self.claims_for_task(profile.task_id)
            if claim.kind is not ClaimKind.CORE
            and claim.profile_condition is not None
            and claim.profile_condition.matches(profile)
        )


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 fingerprint of one benchmark file."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    result = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}:{line_number} must contain a JSON object")
        result.append(payload)
    return tuple(result)


def _load_splits(path: Path) -> tuple[BenchmarkSplit, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_splits = _required_object(payload, "splits")
    return tuple(
        BenchmarkSplit(
            name=name,
            task_ids=_validated_string_list(task_ids, f"splits.{name}"),
        )
        for name, task_ids in sorted(raw_splits.items())
    )


def _validate_file_fingerprints(
    root: Path,
    manifest: ConfirmatoryManifest,
) -> None:
    fingerprints = {item.path: item.sha256 for item in manifest.fingerprints}
    if set(fingerprints) != set(_DATA_FILES):
        raise ValueError("manifest must fingerprint every v3 data file")
    for filename, expected in fingerprints.items():
        if file_sha256(root / filename) != expected:
            raise ValueError(f"benchmark file fingerprint mismatch: {filename}")


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _required_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _non_negative_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_int(payload: dict[str, Any], field: str) -> int:
    value = _non_negative_int(payload, field)
    if value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _string_tuple(payload: dict[str, Any], field: str) -> tuple[str, ...]:
    return _validated_string_list(payload.get(field), field)


def _non_empty_string_tuple(
    payload: dict[str, Any],
    field: str,
) -> tuple[str, ...]:
    values = _string_tuple(payload, field)
    if not values:
        raise ValueError(f"{field} must not be empty")
    return values


def _validated_string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    stripped = tuple(item.strip() for item in value)
    if len(stripped) != len(set(stripped)):
        raise ValueError(f"{field} must not contain duplicates")
    return stripped
