"""Typed fixed-snapshot evidence and claim-level support contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class SupportStatus(str, Enum):
    """Manual or independently judged support relation for one claim/source pair."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    CONTRADICTED = "contradicted"
    MISSING = "missing"


_FORBIDDEN_SOURCE_FIELDS = frozenset(
    {
        "evidence_context",
        "header",
        "purpose",
        "query",
        "target_requirements",
    }
)


@dataclass(frozen=True)
class SnapshotSource:
    """A stable source excerpt that contains no planner metadata."""

    source_id: str
    task_id: str
    title: str
    url: str
    provider: str
    captured_at: str
    text: str
    sha256: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SnapshotSource:
        """Validate and build a source from a JSON object."""

        forbidden = _FORBIDDEN_SOURCE_FIELDS.intersection(payload)
        if forbidden:
            fields = ", ".join(sorted(forbidden))
            raise ValueError(f"snapshot source contains planner leakage fields: {fields}")
        source = cls(
            source_id=_required_string(payload, "source_id"),
            task_id=_required_string(payload, "task_id"),
            title=_required_string(payload, "title"),
            url=_required_string(payload, "url"),
            provider=_required_string(payload, "provider"),
            captured_at=_required_string(payload, "captured_at"),
            text=_required_string(payload, "text"),
            sha256=_required_string(payload, "sha256"),
        )
        if source.sha256 != source.compute_sha256():
            raise ValueError(f"snapshot source checksum mismatch: {source.source_id}")
        return source

    def compute_sha256(self) -> str:
        """Return the checksum of the immutable source payload."""

        payload = "\n".join(
            (
                self.source_id,
                self.task_id,
                self.title,
                self.url,
                self.provider,
                self.captured_at,
                self.text,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str]:
        """Serialize the source without planner query or label fields."""

        return {
            "source_id": self.source_id,
            "task_id": self.task_id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "captured_at": self.captured_at,
            "text": self.text,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ClaimAnnotation:
    """Independent claim/source annotation used by the offline evaluator."""

    task_id: str
    requirement_id: str
    source_id: str
    status: SupportStatus

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClaimAnnotation:
        """Build a typed annotation from JSON."""

        return cls(
            task_id=_required_string(payload, "task_id"),
            requirement_id=_required_string(payload, "requirement_id"),
            source_id=_required_string(payload, "source_id"),
            status=SupportStatus(_required_string(payload, "status")),
        )

    def to_dict(self) -> dict[str, str]:
        """Serialize an annotation."""

        return {
            "task_id": self.task_id,
            "requirement_id": self.requirement_id,
            "source_id": self.source_id,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class SnapshotManifest:
    """Metadata and integrity contract for a fixed evidence snapshot."""

    snapshot_id: str
    schema_version: int
    captured_at: str
    task_ids: tuple[str, ...]
    source_count: int
    annotation_count: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SnapshotManifest:
        """Build a manifest and validate its basic shape."""

        task_ids = payload.get("task_ids")
        if not isinstance(task_ids, list) or not all(isinstance(item, str) for item in task_ids):
            raise ValueError("manifest.task_ids must be a list of strings")
        return cls(
            snapshot_id=_required_string(payload, "snapshot_id"),
            schema_version=int(payload.get("schema_version", 0)),
            captured_at=_required_string(payload, "captured_at"),
            task_ids=tuple(task_ids),
            source_count=int(payload.get("source_count", -1)),
            annotation_count=int(payload.get("annotation_count", -1)),
        )


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Loaded immutable source and annotation data for offline evaluation."""

    manifest: SnapshotManifest
    sources: tuple[SnapshotSource, ...]
    annotations: tuple[ClaimAnnotation, ...]

    @classmethod
    def load(cls, directory: str | Path) -> EvidenceSnapshot:
        """Load and validate a snapshot directory."""

        root = Path(directory)
        manifest = SnapshotManifest.from_dict(json.loads((root / "manifest.json").read_text(encoding="utf-8")))
        sources = tuple(
            SnapshotSource.from_dict(json.loads(line))
            for line in (root / "sources.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        annotations = tuple(
            ClaimAnnotation.from_dict(json.loads(line))
            for line in (root / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        _validate_snapshot(manifest, sources, annotations)
        return cls(manifest=manifest, sources=sources, annotations=annotations)

    def source_ids_for_task(self, task_id: str) -> frozenset[str]:
        """Return stable source IDs available for one task."""

        return frozenset(source.source_id for source in self.sources if source.task_id == task_id)

    def annotation_map(self) -> dict[tuple[str, str, str], SupportStatus]:
        """Return annotations keyed by task, requirement, and source."""

        return {(item.task_id, item.requirement_id, item.source_id): item.status for item in self.annotations}


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_snapshot(
    manifest: SnapshotManifest,
    sources: tuple[SnapshotSource, ...],
    annotations: tuple[ClaimAnnotation, ...],
) -> None:
    if manifest.schema_version != 1:
        raise ValueError(f"unsupported snapshot schema version: {manifest.schema_version}")
    if manifest.source_count != len(sources):
        raise ValueError("manifest.source_count does not match sources.jsonl")
    if manifest.annotation_count != len(annotations):
        raise ValueError("manifest.annotation_count does not match annotations.jsonl")
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("snapshot source_id values must be unique")
    task_ids = set(manifest.task_ids)
    if any(source.task_id not in task_ids for source in sources):
        raise ValueError("source task_id is absent from manifest.task_ids")
    available = {(source.task_id, source.source_id) for source in sources}
    if any((item.task_id, item.source_id) not in available for item in annotations):
        raise ValueError("annotation references an unknown source")
