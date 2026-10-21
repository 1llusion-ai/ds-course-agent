"""Typed course resource contracts and a read-only resource catalogue.

The catalogue is deliberately a small data boundary.  It describes which
resources belong to a course and the identity of its retrieval index, but it
does not open PDFs, initialise Chroma, or alter the current runtime wiring.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic_core import core_schema

CourseResourceStatus = Literal["ready", "unready"]

_COURSE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9][a-z0-9-]{0,61}[a-z0-9])?$")
_REVISION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}$")
_MANIFEST_SCHEMA = "course-resources/1.0"

# The first course remains the compatibility scope for persisted teaching and
# assessment data.  New callers may pass an explicit ``CourseId`` while old
# records and APIs continue to resolve here.
DEFAULT_COURSE_ID = "data-science-intro"


class CourseId(str):
    """Stable, URL-safe identity for a course.

    Human-readable names belong in :class:`CourseResourceManifest`; an ID is
    deliberately lowercase and immutable so it is safe in paths and cache
    keys.
    """

    def __new__(cls, value: str) -> CourseId:
        normalized = str(value or "").strip().lower()
        if not _COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("course_id must be lowercase slug text (2-63 characters)")
        return str.__new__(cls, normalized)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        """Validate explicit course identities at HTTP and storage boundaries."""

        return core_schema.no_info_after_validator_function(cls, core_schema.str_schema())


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _revision(value: object, field_name: str = "revision") -> str:
    text = _required_text(value, field_name)
    if not _REVISION_PATTERN.fullmatch(text):
        raise ValueError(f"{field_name} contains unsupported characters")
    return text


@dataclass(frozen=True, slots=True)
class CourseIndexBinding:
    """Identity and location of one course's retrieval index.

    Paths are stored as declarations and remain relative to the repository by
    convention.  Resolving or opening them belongs to a later composition
    stage, which keeps catalogue loading side-effect free.
    """

    collection_name: str
    persist_directory: str
    manifest_path: str
    revision: str
    embedding_model: str
    metadata_schema_version: str = "retrieval-provenance/1.0"

    def __post_init__(self) -> None:
        for name in ("collection_name", "persist_directory", "manifest_path", "embedding_model"):
            _required_text(getattr(self, name), name)
        _revision(self.revision)
        _required_text(self.metadata_schema_version, "metadata_schema_version")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CourseIndexBinding:
        _reject_unknown(
            payload,
            {
                "collection_name",
                "persist_directory",
                "manifest_path",
                "revision",
                "embedding_model",
                "metadata_schema_version",
            },
        )
        return cls(
            collection_name=payload.get("collection_name", ""),
            persist_directory=payload.get("persist_directory", ""),
            manifest_path=payload.get("manifest_path", ""),
            revision=payload.get("revision", ""),
            embedding_model=payload.get("embedding_model", ""),
            metadata_schema_version=payload.get("metadata_schema_version", "retrieval-provenance/1.0"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "collection_name": self.collection_name,
            "persist_directory": self.persist_directory,
            "manifest_path": self.manifest_path,
            "revision": self.revision,
            "embedding_model": self.embedding_model,
            "metadata_schema_version": self.metadata_schema_version,
        }


@dataclass(frozen=True, slots=True)
class CourseScopeTerm:
    """Textbook topic absent from graph/TOC titles; never a concept alias."""

    term: str
    section: str
    book_page: int
    source_page: int

    def __post_init__(self) -> None:
        if not isinstance(self.term, str) or not isinstance(self.section, str):
            raise TypeError("scope term and section must be text")
        _required_text(self.term, "scope term")
        _required_text(self.section, "scope section")
        if any(type(page) is not int or page <= 0 for page in (self.book_page, self.source_page)):
            raise ValueError("scope term pages must be positive integers")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CourseScopeTerm:
        _reject_unknown(payload, {"term", "section", "book_page", "source_page"})
        return cls(**payload)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "term": self.term,
            "section": self.section,
            "book_page": self.book_page,
            "source_page": self.source_page,
        }


@dataclass(frozen=True, slots=True)
class CourseResourceManifest:
    """Versioned declaration of all resources owned by one course."""

    course_id: CourseId
    display_name: str
    description: str
    revision: str
    status: CourseResourceStatus
    prompt_path: str = ""
    knowledge_graph_path: str = ""
    toc_path: str = ""
    schedule_path: str = ""
    index: CourseIndexBinding | None = None
    resource_metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = _MANIFEST_SCHEMA
    scope_terms: tuple[CourseScopeTerm, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.course_id, CourseId):
            object.__setattr__(self, "course_id", CourseId(str(self.course_id)))
        if not isinstance(self.scope_terms, tuple) or any(
            not isinstance(term, CourseScopeTerm) for term in self.scope_terms
        ):
            raise TypeError("scope_terms must be a tuple of CourseScopeTerm")
        _required_text(self.display_name, "display_name")
        _required_text(self.description, "description")
        _revision(self.revision)
        if self.status not in ("ready", "unready"):
            raise ValueError("status must be 'ready' or 'unready'")
        if self.schema_version != _MANIFEST_SCHEMA:
            raise ValueError(f"unsupported course resource schema: {self.schema_version}")
        if self.status == "ready" and self.index is None:
            raise ValueError("ready courses must declare an index binding")
        if not isinstance(self.resource_metadata, Mapping):
            raise TypeError("resource_metadata must be an object")
        object.__setattr__(self, "resource_metadata", MappingProxyType(dict(self.resource_metadata)))
        for name in ("prompt_path", "knowledge_graph_path", "toc_path", "schedule_path"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be text")

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def index_binding(self) -> CourseIndexBinding | None:
        """Descriptive alias for callers that prefer the explicit name."""

        return self.index

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CourseResourceManifest:
        _reject_unknown(
            payload,
            {
                "schema_version",
                "course_id",
                "display_name",
                "description",
                "revision",
                "status",
                "prompt_path",
                "knowledge_graph_path",
                "toc_path",
                "schedule_path",
                "index",
                "resource_metadata",
                "scope_terms",
            },
        )
        raw_index = payload.get("index")
        if raw_index is not None and not isinstance(raw_index, Mapping):
            raise TypeError("index must be an object or null")
        raw_terms = payload.get("scope_terms", [])
        if not isinstance(raw_terms, list) or any(not isinstance(term, Mapping) for term in raw_terms):
            raise TypeError("scope_terms must be an array of objects")
        raw_metadata = payload.get("resource_metadata", {})
        if not isinstance(raw_metadata, Mapping):
            raise TypeError("resource_metadata must be an object")
        return cls(
            schema_version=payload.get("schema_version", _MANIFEST_SCHEMA),
            course_id=CourseId(payload.get("course_id", "")),
            display_name=payload.get("display_name", ""),
            description=payload.get("description", ""),
            revision=payload.get("revision", ""),
            status=payload.get("status", "unready"),
            prompt_path=payload.get("prompt_path", ""),
            knowledge_graph_path=payload.get("knowledge_graph_path", ""),
            toc_path=payload.get("toc_path", ""),
            schedule_path=payload.get("schedule_path", ""),
            index=CourseIndexBinding.from_dict(raw_index) if raw_index is not None else None,
            resource_metadata=dict(raw_metadata),
            scope_terms=tuple(CourseScopeTerm.from_dict(term) for term in raw_terms),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "course_id": str(self.course_id),
            "display_name": self.display_name,
            "description": self.description,
            "revision": self.revision,
            "status": self.status,
            "prompt_path": self.prompt_path,
            "knowledge_graph_path": self.knowledge_graph_path,
            "toc_path": self.toc_path,
            "schedule_path": self.schedule_path,
            "index": self.index.to_dict() if self.index is not None else None,
            "resource_metadata": dict(self.resource_metadata),
            "scope_terms": [term.to_dict() for term in self.scope_terms],
        }


@dataclass(frozen=True, slots=True)
class ResolvedCourse:
    """One turn's immutable catalogue result, including explicit resolution failure.

    Teaching builds scope vocabulary from the selected course resources. An empty
    vocabulary grants no extra scope; it never borrows another course's graph.
    """

    requested_id: CourseId
    manifest: CourseResourceManifest | None = None
    scope_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.requested_id, CourseId):
            object.__setattr__(self, "requested_id", CourseId(self.requested_id))
        if self.manifest is not None and not isinstance(self.manifest, CourseResourceManifest):
            raise TypeError("manifest must be CourseResourceManifest or None")
        if not isinstance(self.scope_terms, tuple) or any(
            not isinstance(term, str) or not term.strip() for term in self.scope_terms
        ):
            raise TypeError("scope_terms must be a tuple of non-empty text")
        if self.manifest is None and self.scope_terms:
            raise ValueError("unresolved courses cannot declare scope vocabulary")
        if self.manifest is not None and not self.manifest.is_ready and self.scope_terms:
            raise ValueError("unready courses cannot declare resolved scope vocabulary")
        if self.manifest is not None and self.manifest.course_id != self.requested_id:
            raise ValueError("resolved manifest must match requested course")

    @property
    def display_name(self) -> str:
        return self.manifest.display_name if self.manifest is not None else "当前课程"


@dataclass(frozen=True, slots=True)
class CourseContext:
    """Explicit course identity carried by a future turn composition root."""

    course_id: CourseId
    resource_revision: str | None = None
    student_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.course_id, CourseId):
            object.__setattr__(self, "course_id", CourseId(str(self.course_id)))
        if self.resource_revision is not None:
            _revision(self.resource_revision, "resource_revision")
        for name in ("student_id", "session_id", "turn_id"):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} cannot be blank when supplied")


def _reject_unknown(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown course resource fields: {', '.join(unknown)}")


class CourseCatalog:
    """Immutable collection of course resource manifests."""

    def __init__(self, manifests: list[CourseResourceManifest] | tuple[CourseResourceManifest, ...]) -> None:
        values = tuple(manifests)
        by_id: dict[CourseId, CourseResourceManifest] = {}
        for manifest in values:
            if not isinstance(manifest, CourseResourceManifest):
                raise TypeError("catalog entries must be CourseResourceManifest instances")
            if manifest.course_id in by_id:
                raise ValueError(f"duplicate course_id: {manifest.course_id}")
            by_id[manifest.course_id] = manifest
        object.__setattr__(self, "_manifests", values)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    @classmethod
    def from_directory(cls, directory: str | Path) -> CourseCatalog:
        root = Path(directory)
        if not root.is_dir():
            raise FileNotFoundError(f"course catalogue directory does not exist: {root}")
        manifests = []
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid course manifest JSON: {path}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"course manifest must be a JSON object: {path}")
            manifests.append(CourseResourceManifest.from_dict(payload))
        return cls(manifests)

    def list(self) -> tuple[CourseResourceManifest, ...]:
        return self._manifests

    def get(self, course_id: CourseId | str) -> CourseResourceManifest | None:
        try:
            normalized = course_id if isinstance(course_id, CourseId) else CourseId(course_id)
        except (TypeError, ValueError):
            return None
        return self._by_id.get(normalized)

    def require(self, course_id: CourseId | str) -> CourseResourceManifest:
        manifest = self.get(course_id)
        if manifest is None:
            raise KeyError(f"unknown course_id: {course_id}")
        return manifest


class CourseResolver:
    """Resolve course IDs and create explicit contexts without mutating state."""

    def __init__(self, catalog: CourseCatalog, default_course_id: CourseId | str | None = None) -> None:
        self.catalog = catalog
        self.default_course_id = CourseId(default_course_id) if default_course_id is not None else None
        if self.default_course_id is not None:
            catalog.require(self.default_course_id)

    def resolve(self, course_id: CourseId | str | None = None) -> CourseResourceManifest:
        selected = course_id if course_id is not None else self.default_course_id
        if selected is None:
            raise ValueError("course_id is required when no default course is configured")
        return self.catalog.require(selected)

    def context(
        self,
        course_id: CourseId | str | None = None,
        *,
        student_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> CourseContext:
        manifest = self.resolve(course_id)
        return CourseContext(
            course_id=manifest.course_id,
            resource_revision=manifest.revision,
            student_id=student_id,
            session_id=session_id,
            turn_id=turn_id,
        )


__all__ = [
    "CourseCatalog",
    "CourseContext",
    "CourseId",
    "CourseIndexBinding",
    "CourseResourceManifest",
    "CourseResolver",
    "CourseResourceStatus",
    "CourseScopeTerm",
    "ResolvedCourse",
    "DEFAULT_COURSE_ID",
]
