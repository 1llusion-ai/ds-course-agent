"""Validate production context and complete prompt budgets on frozen rankings."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import chromadb
from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field, model_validator

import ds_course_agent.shared.config as config
from benchmarks.retrieval_strategy_schema import RetrievalStrategyReport
from ds_course_agent.retrieval.context_assembler import (
    ChunkProvenance,
    ContextAssemblyConfig,
    RankedContextCandidate,
    assemble_context,
    load_token_counter,
)
from ds_course_agent.retrieval.index_manifest import IndexArtifact, PromotedIndexManifest
from ds_course_agent.retrieval.service import build_rag_prompt_template


class PromptBudgetRow(BaseModel):
    """One frozen query measured with the production context and prompt policy."""

    model_config = ConfigDict(extra="forbid")

    id: str
    split: str
    query: str
    selected_document_count: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    answer_reserved_tokens: int = Field(gt=0)
    complete_tokens: int = Field(gt=0)
    remaining_tokens: int = Field(ge=0)
    stopped_on_overflow: bool
    selected_source_pages: list[int]

    @model_validator(mode="after")
    def validate_token_totals(self) -> PromptBudgetRow:
        """Reject stale row-level token arithmetic."""
        if self.complete_tokens != self.prompt_tokens + self.answer_reserved_tokens:
            raise ValueError("complete_tokens must equal prompt_tokens plus answer_reserved_tokens")
        return self


class ProductionPromptBudgetReport(BaseModel):
    """Complete prompt-budget proof for frozen dev and test retrieval rankings."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^retrieval-production-prompt-budget/1\.0$")
    created_at: datetime
    promoted_index_manifest: IndexArtifact
    retrieval_reports: list[IndexArtifact]
    tokenizer_policy: str
    candidate_depth: int
    context_token_budget: int
    answer_reserved_tokens: int
    context_window_tokens: int
    query_count: int = Field(gt=0)
    maximum_context_tokens: int
    maximum_prompt_tokens: int
    maximum_complete_tokens: int
    minimum_remaining_tokens: int
    rows: list[PromptBudgetRow] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report_totals(self) -> ProductionPromptBudgetReport:
        """Keep report aggregates and per-query budgets internally consistent."""
        if self.query_count != len(self.rows):
            raise ValueError("query_count is stale")
        identities = [(row.split, row.id) for row in self.rows]
        if len(identities) != len(set(identities)):
            raise ValueError("prompt budget rows contain duplicate split/query identities")
        for row in self.rows:
            if row.answer_reserved_tokens != self.answer_reserved_tokens:
                raise ValueError("row answer reserve differs from report policy")
            if row.context_tokens > self.context_token_budget:
                raise ValueError("row context exceeds report context token budget")
            if row.complete_tokens > self.context_window_tokens:
                raise ValueError("row complete prompt exceeds report context window")
            if row.remaining_tokens != self.context_window_tokens - row.complete_tokens:
                raise ValueError("row remaining_tokens is stale")
            if row.selected_document_count > self.candidate_depth:
                raise ValueError("row selected document count exceeds candidate depth")
        if self.maximum_context_tokens != max(row.context_tokens for row in self.rows):
            raise ValueError("maximum_context_tokens is stale")
        if self.maximum_prompt_tokens != max(row.prompt_tokens for row in self.rows):
            raise ValueError("maximum_prompt_tokens is stale")
        if self.maximum_complete_tokens != max(row.complete_tokens for row in self.rows):
            raise ValueError("maximum_complete_tokens is stale")
        if self.minimum_remaining_tokens != min(row.remaining_tokens for row in self.rows):
            raise ValueError("minimum_remaining_tokens is stale")
        return self


def _artifact(root: Path, path: Path) -> IndexArtifact:
    resolved = path.resolve()
    return IndexArtifact(
        path=resolved.relative_to(root.resolve()).as_posix(),
        sha256=hashlib.sha256(resolved.read_bytes()).hexdigest(),
    )


def _load_documents(collection, chunk_ids: list[str]) -> dict[str, Document]:
    payload = collection.get(ids=chunk_ids, include=["documents", "metadatas"])
    documents = {
        chunk_id: Document(page_content=document, metadata=metadata)
        for chunk_id, document, metadata in zip(
            payload.get("ids") or [],
            payload.get("documents") or [],
            payload.get("metadatas") or [],
            strict=True,
        )
    }
    if set(documents) != set(chunk_ids):
        raise ValueError("promoted collection did not return every frozen ranked chunk")
    return documents


def validate_production_prompt_budget(
    *,
    root: Path,
    promoted_manifest_path: Path,
    retrieval_report_paths: list[Path],
    output: Path,
    now: datetime | None = None,
) -> ProductionPromptBudgetReport:
    """Measure every frozen Top-10 context and reject any complete prompt overflow."""
    root = root.resolve()
    promoted_manifest_path = promoted_manifest_path.resolve()
    output = output.resolve()
    if not output.is_relative_to(root / "var" / "artifacts" / "kb_eval"):
        raise ValueError("prompt budget report must be under var/artifacts/kb_eval")
    if output.exists():
        raise ValueError("prompt budget report already exists; refusing overwrite")

    promoted = PromotedIndexManifest.model_validate_json(promoted_manifest_path.read_bytes())
    reports = [RetrievalStrategyReport.model_validate_json(path.read_bytes()) for path in retrieval_report_paths]
    required_depth = int(config.RAG_CANDIDATE_DEPTH)
    for report in reports:
        if report.strategy.retrieval_mode != "vector":
            raise ValueError("production prompt validation requires raw vector rankings")
        if any(
            (
                report.strategy.query_instruction is not None,
                report.strategy.reranker_model is not None,
                report.strategy.routing_policy is not None,
            )
        ):
            raise ValueError("production prompt validation rejects instructed, reranked, or routed rankings")
        if report.strategy.candidate_depth < required_depth or any(
            len(query.retrieved) < required_depth for query in report.queries
        ):
            raise ValueError(f"production prompt validation requires Top-{required_depth} rankings for every query")

    client = chromadb.PersistentClient(path=str(root / promoted.persist_directory))
    collection = client.get_collection(promoted.destination_collection)
    if collection.count() != promoted.document_count:
        raise ValueError("promoted collection count differs from its manifest")
    chunk_ids = list(
        dict.fromkeys(item.chunk_id for report in reports for query in report.queries for item in query.retrieved[:10])
    )
    documents = _load_documents(collection, chunk_ids)
    counter = load_token_counter(root / "var" / "cache" / "tiktoken")
    context_config = ContextAssemblyConfig(
        token_budget=int(config.RAG_CONTEXT_MAX_TOKENS),
        candidate_depth=int(config.RAG_CANDIDATE_DEPTH),
        tokenizer_policy=str(config.RAG_CONTEXT_TOKENIZER_POLICY),
        deduplication_mode=str(config.RAG_CONTEXT_DEDUPLICATION_MODE),
        overflow_policy=str(config.RAG_CONTEXT_OVERFLOW_POLICY),
        header_policy=str(config.RAG_CONTEXT_HEADER_POLICY),
    )
    prompt_template = build_rag_prompt_template()
    answer_reserved = int(config.RAG_ANSWER_MAX_TOKENS)
    context_window = int(config.CONTEXT_WINDOW_TOKENS)
    rows: list[PromptBudgetRow] = []
    for report in reports:
        for query in report.queries:
            candidates = [
                RankedContextCandidate(
                    document=documents[item.chunk_id],
                    retrieval_rank=item.rank,
                    distance=max(0.0, 1.0 - item.ranking_score),
                    provenance=ChunkProvenance.from_document(documents[item.chunk_id]),
                )
                for item in query.retrieved[: context_config.candidate_depth]
            ]
            assembly = assemble_context(candidates, config=context_config, token_counter=counter)
            prompt = prompt_template.format(context=assembly.formatted_context, input=query.query)
            if config.CHAT_SYSTEM_SUFFIX:
                prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
            prompt_tokens = counter.count(prompt)
            complete_tokens = prompt_tokens + answer_reserved
            if complete_tokens > context_window:
                raise ValueError(
                    f"complete production prompt exceeds context window for {query.id}: "
                    f"{complete_tokens} > {context_window}"
                )
            rows.append(
                PromptBudgetRow(
                    id=query.id,
                    split=report.split,
                    query=query.query,
                    selected_document_count=len(assembly.selected),
                    context_tokens=assembly.used_tokens,
                    prompt_tokens=prompt_tokens,
                    answer_reserved_tokens=answer_reserved,
                    complete_tokens=complete_tokens,
                    remaining_tokens=context_window - complete_tokens,
                    stopped_on_overflow=assembly.stopped_on_overflow,
                    selected_source_pages=list(
                        dict.fromkeys(
                            fragment.interval.source_page
                            for selected in assembly.selected
                            for fragment in selected.fragments
                        )
                    ),
                )
            )
    client.close()

    report = ProductionPromptBudgetReport(
        schema_version="retrieval-production-prompt-budget/1.0",
        created_at=now or datetime.now().astimezone(),
        promoted_index_manifest=_artifact(root, promoted_manifest_path),
        retrieval_reports=[_artifact(root, path) for path in retrieval_report_paths],
        tokenizer_policy=counter.policy_version,
        candidate_depth=context_config.candidate_depth,
        context_token_budget=context_config.token_budget,
        answer_reserved_tokens=answer_reserved,
        context_window_tokens=context_window,
        query_count=len(rows),
        maximum_context_tokens=max(row.context_tokens for row in rows),
        maximum_prompt_tokens=max(row.prompt_tokens for row in rows),
        maximum_complete_tokens=max(row.complete_tokens for row in rows),
        minimum_remaining_tokens=min(row.remaining_tokens for row in rows),
        rows=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """Validate the frozen dev/test rankings against one promoted index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted-index-manifest", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = validate_production_prompt_budget(
        root=args.root,
        promoted_manifest_path=args.promoted_index_manifest,
        retrieval_report_paths=args.retrieval_report,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "query_count": report.query_count,
                "maximum_context_tokens": report.maximum_context_tokens,
                "maximum_complete_tokens": report.maximum_complete_tokens,
                "minimum_remaining_tokens": report.minimum_remaining_tokens,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
