from __future__ import annotations

from pathlib import Path

import pytest

from ds_course_agent.courses import CourseCatalog
from ds_course_agent.kb.ingestion import (
    CourseMaterialImporter,
    ImportJobStore,
    ImportStage,
    ImportStatus,
    sanitize_text_for_storage,
)
from ds_course_agent.kb.toc_parser import TOCParser
from scripts.build_course_candidate import build_candidate


def _catalog() -> CourseCatalog:
    return CourseCatalog.from_directory("data/courses")


def _importer(tmp_path: Path) -> tuple[CourseMaterialImporter, Path]:
    source_root = tmp_path / "var" / "course_sources"
    source_root.mkdir(parents=True)
    artifact_root = tmp_path / "var" / "artifacts" / "course_imports"
    importer = CourseMaterialImporter(
        catalog=_catalog(),
        source_root=source_root,
        artifact_root=artifact_root,
        store=ImportJobStore(artifact_root / "jobs"),
    )
    return importer, source_root


def test_digital_literacy_uses_its_published_course_index() -> None:
    manifest = _catalog().require("digital-literacy")

    assert manifest.is_ready
    assert manifest.index_binding is not None
    assert manifest.index_binding.collection_name == "digital_literacy_7c516f878df0e9b2_student_v1"
    assert manifest.resource_metadata["source"]["path"] == "var/course_sources/digital-literacy-course.pdf"


def test_course_toc_adapter_uses_textbook_page_coordinates() -> None:
    parser = TOCParser("data/courses/digital-literacy/toc.json")

    assert parser.sections[0].number == "第1章"
    assert parser.sections[0].page == 1
    assert parser.sections[0].name == "数字素养"
    assert parser.sections[1].page == 38
    assert parser.sections[-1].name == "参考文献"


def test_candidate_builder_requires_marker_for_formal_index(tmp_path: Path) -> None:
    source_root = tmp_path / "var" / "course_sources"
    source_root.mkdir(parents=True)
    source = source_root / "book.pdf"
    source.write_bytes(b"%PDF-1.4\nsource")

    # The formal candidate path cannot silently downgrade to the pypdf baseline.
    with pytest.raises(ValueError, match="parser_mode=marker"):
        build_candidate(course_id="digital-literacy", source=source, parser_mode="pypdf-plain")


def test_create_job_rejects_sources_outside_controlled_directory(tmp_path: Path) -> None:
    importer, source_root = _importer(tmp_path)
    inside = source_root / "book.pdf"
    inside.write_bytes(b"%PDF-1.4\ninside")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\noutside")

    job = importer.create_job("digital-literacy", inside)
    assert job.status == ImportStatus.QUEUED
    assert job.source_path.endswith("var/course_sources/book.pdf")
    assert job.version.startswith("sha256-")
    assert importer.store.get(job.job_id).source_sha256 == job.source_sha256

    with pytest.raises(ValueError, match="受控目录"):
        importer.create_job("digital-literacy", outside)


def test_import_pipeline_persists_stage_trace_and_failed_state(tmp_path: Path) -> None:
    importer, source_root = _importer(tmp_path)
    source = source_root / "book.pdf"
    source.write_bytes(b"%PDF-1.4\nsource")
    job = importer.create_job("digital-literacy", source)

    def complete(stage: ImportStage):
        def handler(_job, _outputs):
            return {"stage": stage.value}, {"count": 1}

        return handler

    complete_handlers = {stage: complete(stage) for stage in ImportStage}
    completed = importer.run(job.job_id, handlers=complete_handlers)
    assert completed.status == ImportStatus.INDEX_READY
    assert all(item.status == "completed" for item in completed.stages.values())
    assert Path(completed.stages[ImportStage.INDEX_READY.value].artifact_path).is_file()

    failed_job = importer.create_job("digital-literacy", source)

    def fail(_job, _outputs):
        raise RuntimeError("extractor unavailable")

    failed = importer.run(
        failed_job.job_id,
        handlers={ImportStage.INSPECT: complete(ImportStage.INSPECT), ImportStage.EXTRACT: fail},
    )
    assert failed.status == ImportStatus.FAILED
    assert failed.current_stage == ImportStage.EXTRACT.value
    assert failed.stages[ImportStage.EXTRACT.value].status == "failed"
    assert failed.error == "extract: extractor unavailable"
    assert importer.store.get(failed.job_id).status == ImportStatus.FAILED


def test_surrogates_are_cleaned_before_extract_artifact_persistence(tmp_path: Path) -> None:
    importer, source_root = _importer(tmp_path)
    source = source_root / "book.pdf"
    source.write_bytes(b"%PDF-1.4\nsource")
    job = importer.create_job("digital-literacy", source)

    assert sanitize_text_for_storage("a\ud800b\udc00c\ud83d\ude00") == "a�b�c😀"

    def complete(stage: ImportStage):
        return lambda _job, _outputs: ({"stage": stage.value}, {"count": 1})

    def malformed_extract(_job, _outputs):
        return {"parser": "test", "pages": [{"page_num": 1, "text": "保留\ud800字符"}]}, {}

    completed = importer.run(
        job.job_id,
        handlers={
            ImportStage.INSPECT: complete(ImportStage.INSPECT),
            ImportStage.EXTRACT: malformed_extract,
            ImportStage.CHUNK: complete(ImportStage.CHUNK),
            ImportStage.INDEX_READY: complete(ImportStage.INDEX_READY),
        },
    )
    assert completed.status == ImportStatus.INDEX_READY
    extract_path = Path(completed.stages[ImportStage.EXTRACT.value].artifact_path)
    extract_text = extract_path.read_text(encoding="utf-8")
    assert "保留�字符" in extract_text
    assert "\ud800" not in extract_text
