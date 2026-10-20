"""Management-side course material ingestion contracts.

This module owns the offline material import boundary.  Student requests only
consume a published course manifest and never call these functions.  An import
is represented by a persisted job and a content-addressed resource version;
the stage handlers are deliberately injectable so a future worker can replace
the local runner without creating a second pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ds_course_agent.courses import CourseCatalog, CourseId
from ds_course_agent.shared.paths import PROJECT_ROOT

SOURCE_ROOT = PROJECT_ROOT / "var" / "course_sources"
IMPORT_ARTIFACT_ROOT = PROJECT_ROOT / "var" / "artifacts" / "course_imports"
_JOB_ID_PATTERN = re.compile(r"^[a-f0-9-]{16,64}$")


class ImportStage(str, Enum):
    """Ordered stages of one material import."""

    INSPECT = "inspect"
    EXTRACT = "extract"
    CHUNK = "chunk"
    INDEX_READY = "index_ready"


class ImportStatus(str, Enum):
    """Lifecycle state of an imported resource version."""

    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    INDEX_READY = "index_ready"
    FAILED = "failed"


@dataclass
class StageResult:
    """Persisted outcome of one pipeline stage."""

    stage: str
    status: str = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    artifact_path: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ImportJob:
    """A course-scoped resource version and its traceable import state."""

    job_id: str
    course_id: str
    version: str
    source_path: str
    source_sha256: str
    source_size: int
    created_at: str
    updated_at: str
    status: str = ImportStatus.QUEUED
    current_stage: str | None = None
    artifact_dir: str = ""
    stages: dict[str, StageResult] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stages"] = {name: asdict(result) for name, result in self.stages.items()}
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ImportJob:
        stages = {name: StageResult(**dict(result)) for name, result in dict(payload.get("stages") or {}).items()}
        values = dict(payload)
        values["stages"] = stages
        return cls(**values)


StageHandler = Callable[[ImportJob, Mapping[str, Any]], tuple[Any, Mapping[str, Any]]]


class ImportJobStore:
    """Small atomic JSON store for management-side import jobs."""

    def __init__(self, root: str | Path = IMPORT_ARTIFACT_ROOT / "jobs") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        if not _JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError("invalid import job id")
        return self.root / f"{job_id}.json"

    def save(self, job: ImportJob) -> ImportJob:
        path = self._path(job.job_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return job

    def get(self, job_id: str) -> ImportJob:
        path = self._path(job_id)
        if not path.is_file():
            raise KeyError(f"unknown import job: {job_id}")
        try:
            return ImportJob.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid import job state: {path}") from exc

    def list(self, *, course_id: str | None = None) -> tuple[ImportJob, ...]:
        jobs = []
        for path in sorted(self.root.glob("*.json")):
            try:
                job = self.get(path.stem)
            except (KeyError, RuntimeError):
                continue
            if course_id is None or job.course_id == str(course_id):
                jobs.append(job)
        return tuple(jobs)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize_text_for_storage(text: str) -> str:
    """Replace lone UTF-16 surrogate code points before UTF-8 persistence.

    PDF extractors occasionally return lone surrogates from malformed embedded
    fonts.  A valid pair is reconstructed as its code point; an unpaired code
    point becomes U+FFFD, which records an unknown character without inventing
    replacement text or allowing ``UnicodeEncodeError`` during artifact writes.
    """

    result: list[str] = []
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 < len(text):
                next_codepoint = ord(text[index + 1])
                if 0xDC00 <= next_codepoint <= 0xDFFF:
                    result.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + next_codepoint - 0xDC00))
                    index += 2
                    continue
            result.append("\ufffd")
        elif 0xDC00 <= codepoint <= 0xDFFF:
            result.append("\ufffd")
        else:
            result.append(text[index])
        index += 1
    return "".join(result)


def _json_safe(value: Any) -> Any:
    """Convert stage results to JSON without allowing arbitrary objects in state."""

    if isinstance(value, str):
        return sanitize_text_for_storage(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {sanitize_text_for_storage(str(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return sanitize_text_for_storage(str(value))


def _record_path(path: Path) -> str:
    """Use repository-relative paths in production and absolute test paths."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


class CourseMaterialImporter:
    """Create and run course material imports outside the student request path.

    ``create_job`` is intentionally cheap and is the seam an admin API can call
    later.  ``run`` is a local application runner for now; a worker can call
    the same method with the same persisted job ID.  The default runner creates
    an inspect/extract/chunk/index-ready candidate and does not publish it.
    """

    stage_order = tuple(ImportStage)

    def __init__(
        self,
        *,
        catalog: CourseCatalog | None = None,
        source_root: str | Path = SOURCE_ROOT,
        artifact_root: str | Path = IMPORT_ARTIFACT_ROOT,
        store: ImportJobStore | None = None,
        parser_mode: str = "pypdf-plain",
    ) -> None:
        self.catalog = catalog or CourseCatalog.from_directory(PROJECT_ROOT / "data" / "courses")
        self.source_root = Path(source_root).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.store = store or ImportJobStore(self.artifact_root / "jobs")
        self.parser_mode = parser_mode

    def _safe_source(self, source_path: str | Path) -> Path:
        candidate = Path(source_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.source_root)
        except (OSError, ValueError) as exc:
            raise ValueError("教材文件必须位于 var/course_sources 受控目录内") from exc
        if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
            raise ValueError("教材文件必须是 PDF 文件")
        return resolved

    def create_job(self, course_id: str | CourseId, source_path: str | Path) -> ImportJob:
        """Validate a local source and persist a queued content version."""

        course = self.catalog.require(CourseId(str(course_id)))
        source = self._safe_source(source_path)
        digest = _sha256(source)
        version = f"sha256-{digest[:16]}"
        job_id = str(uuid.uuid4())
        artifact_dir = self.artifact_root / str(course.course_id) / version / job_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        relative_source = _record_path(source)
        now = _now()
        job = ImportJob(
            job_id=job_id,
            course_id=str(course.course_id),
            version=version,
            source_path=relative_source,
            source_sha256=digest,
            source_size=source.stat().st_size,
            created_at=now,
            updated_at=now,
            artifact_dir=_record_path(artifact_dir),
            stages={stage.value: StageResult(stage=stage.value) for stage in self.stage_order},
        )
        return self.store.save(job)

    def _source_for(self, job: ImportJob) -> Path:
        return self._safe_source(PROJECT_ROOT / job.source_path)

    def _artifact_dir(self, job: ImportJob) -> Path:
        path = (PROJECT_ROOT / job.artifact_dir).resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ValueError("import artifact path escapes the controlled artifact directory") from exc
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _default_handlers(self) -> dict[ImportStage, StageHandler]:
        return {
            ImportStage.INSPECT: self._inspect,
            ImportStage.EXTRACT: self._extract,
            ImportStage.CHUNK: self._chunk,
            ImportStage.INDEX_READY: self._index_ready,
        }

    def run(self, job_id: str, *, handlers: Mapping[ImportStage | str, StageHandler] | None = None) -> ImportJob:
        """Run the ordered stages and persist every transition and failure."""

        job = self.store.get(job_id)
        selected = self._default_handlers()
        for key, handler in (handlers or {}).items():
            selected[ImportStage(key)] = handler
        outputs: dict[str, Any] = {}
        job.status = ImportStatus.PROCESSING
        job.error = None
        self.store.save(job)

        for stage in self.stage_order:
            result = job.stages[stage.value]
            result.status = "running"
            result.started_at = _now()
            result.error = None
            job.current_stage = stage.value
            job.updated_at = _now()
            self.store.save(job)
            try:
                payload, metrics = selected[stage](job, outputs)
                payload = _json_safe(payload)
                artifact = self._artifact_dir(job) / f"{stage.value}.json"
                artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                outputs[stage.value] = payload
                result.status = "completed"
                result.finished_at = _now()
                result.artifact_path = _record_path(artifact)
                result.metrics = dict(_json_safe(metrics))
                job.updated_at = _now()
                self.store.save(job)
            except Exception as exc:
                result.status = "failed"
                result.finished_at = _now()
                result.error = sanitize_text_for_storage(str(exc))
                job.status = ImportStatus.FAILED
                job.error = f"{stage.value}: {sanitize_text_for_storage(str(exc))}"
                job.updated_at = _now()
                self.store.save(job)
                return job

        job.status = ImportStatus.INDEX_READY
        job.current_stage = ImportStage.INDEX_READY.value
        job.updated_at = _now()
        return self.store.save(job)

    def _inspect(self, job: ImportJob, _: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
        source = self._source_for(job)
        actual_hash = _sha256(source)
        if actual_hash != job.source_sha256:
            raise ValueError("教材文件在导入期间发生变化，请重新创建版本")
        try:
            from pypdf import PdfReader

            pages = len(PdfReader(str(source)).pages)
        except Exception as exc:
            raise ValueError(f"无法读取 PDF: {exc}") from exc
        return (
            {"source_path": job.source_path, "sha256": actual_hash, "bytes": source.stat().st_size, "pages": pages},
            {"pages": pages, "bytes": source.stat().st_size},
        )

    def _extract(self, job: ImportJob, _: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
        from ds_course_agent.kb.parser import parse_pdf_file

        result = parse_pdf_file(str(self._source_for(job)), save_trace=False, parser_mode=self.parser_mode)
        if result.error or not result.pages:
            raise ValueError(result.error or "PDF 未提取出文本")
        pages = [{"page_num": page.page_num, "text": sanitize_text_for_storage(page.text)} for page in result.pages]
        return (
            {"parser": result.parser_mode, "pages": pages},
            {"pages": len(pages), "characters": sum(len(p["text"]) for p in pages)},
        )

    def _chunk(self, job: ImportJob, outputs: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
        pages = outputs.get(ImportStage.EXTRACT.value, {}).get("pages", [])
        chunks: list[dict[str, Any]] = []
        chunk_size = 1300
        for page in pages:
            text = str(page.get("text") or "").strip()
            if not text:
                continue
            start = 0
            while start < len(text):
                end = min(len(text), start + chunk_size)
                content = text[start:end].strip()
                if content:
                    chunks.append(
                        {
                            "content": content,
                            "metadata": {
                                "course_id": job.course_id,
                                "resource_version": job.version,
                                "source": job.source_path,
                                "source_page": int(page["page_num"]),
                                "chunk_type": "semantic",
                            },
                        }
                    )
                if end >= len(text):
                    break
                start = max(start + 1, end - 300)
        return ({"chunks": chunks}, {"chunks": len(chunks), "pages": len(pages)})

    def _index_ready(self, job: ImportJob, outputs: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
        chunks = outputs.get(ImportStage.CHUNK.value, {}).get("chunks", [])
        if not chunks:
            raise ValueError("切块结果为空，需人工检查教材解析质量")
        return (
            {
                "schema_version": "course-import-candidate/1.0",
                "course_id": job.course_id,
                "resource_version": job.version,
                "source_sha256": job.source_sha256,
                "chunk_count": len(chunks),
                "published": False,
            },
            {"chunks": len(chunks), "published": False},
        )


__all__ = [
    "IMPORT_ARTIFACT_ROOT",
    "SOURCE_ROOT",
    "CourseMaterialImporter",
    "ImportJob",
    "ImportJobStore",
    "ImportStage",
    "ImportStatus",
    "StageResult",
    "sanitize_text_for_storage",
]
