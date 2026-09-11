"""Production textbook retrieval and grounded-answer service."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAIEmbeddings

import ds_course_agent.shared.config as config
from ds_course_agent.retrieval.context_assembler import (
    AssembledContext,
    ChunkProvenance,
    ContextAssemblyConfig,
    ContextBudgetError,
    RankedContextCandidate,
    assemble_context,
    clone_assembled_context,
    load_token_counter,
)
from ds_course_agent.retrieval.index_manifest import PromotedIndexManifest
from ds_course_agent.retrieval.term_resolution import (
    COURSE_TERM_POLICY_VERSION,
    CourseTermIndex,
    CourseTermResolution,
)
from ds_course_agent.retrieval.timeouts import retrieval_embedding_timeout_seconds
from ds_course_agent.shared.embeddings import embed_query_cached, embedding_model_kwargs
from ds_course_agent.shared.kb_revision import read_kb_revision
from ds_course_agent.shared.llm import get_rag_text_model
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.shared.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

_NO_CONTEXT = "无相关资料"
_RAG_ANSWER_SYSTEM_PROMPT = (
    "你是数据科学课程助教。只能依据参考材料回答；材料不足时请明确说明。"
    "请给出教学型回答，而不是摘要式短答。默认结构：先用一句话给直接结论，"
    "再解释核心定义/机制，补充一个简单例子或类比，最后指出常见误区或学习建议。"
    "回答应聚焦当前问题，避免无关背景，不要编造教材外信息。参考材料：\n{context}"
)
_RAG_ANSWER_USER_PROMPT = "请基于参考材料认真讲解用户提问：\n{input}"


def build_rag_prompt_template() -> ChatPromptTemplate:
    """Build the single production prompt used for grounded textbook answers."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", _RAG_ANSWER_SYSTEM_PROMPT),
            ("user", _RAG_ANSWER_USER_PROMPT),
        ]
    )


def _warn_large_rag_payload(payload: str, *, location: str, payload_type: str, **metadata) -> None:
    """Emit best-effort large-payload telemetry without changing content."""
    try:
        from ds_course_agent.shared.tool_result_store import maybe_store_large_text_payload

        maybe_store_large_text_payload(
            payload,
            location=location,
            payload_type=payload_type,
            **metadata,
        )
    except Exception:
        logger.debug("Failed to emit RAG payload size warning at %s", location, exc_info=True)


def _trace_rag_event(stage: str, **metadata) -> None:
    """Emit one best-effort retrieval or answer trace event."""
    try:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step(stage, **metadata)
    except Exception:
        logger.debug("Failed to emit RAG trace event at %s", stage, exc_info=True)


def _candidate_depth() -> int:
    return max(1, int(getattr(config, "RAG_CANDIDATE_DEPTH", 10) or 10))


def _context_token_budget() -> int:
    return max(1, int(getattr(config, "RAG_CONTEXT_MAX_TOKENS", 4096) or 4096))


def _context_tokenizer_policy() -> str:
    return str(getattr(config, "RAG_CONTEXT_TOKENIZER_POLICY", "cl100k_base_v1") or "cl100k_base_v1")


def _context_deduplication_mode() -> str:
    return str(
        getattr(config, "RAG_CONTEXT_DEDUPLICATION_MODE", "exact_source_interval_v1") or "exact_source_interval_v1"
    )


def _context_overflow_policy() -> str:
    return str(getattr(config, "RAG_CONTEXT_OVERFLOW_POLICY", "stop_v1") or "stop_v1")


def _context_header_policy() -> str:
    return str(getattr(config, "RAG_CONTEXT_HEADER_POLICY", "compact_page_v1") or "compact_page_v1")


def _answer_max_tokens() -> int:
    return max(1, int(getattr(config, "RAG_ANSWER_MAX_TOKENS", 768) or 768))


def _context_window_tokens() -> int:
    return max(1, int(getattr(config, "CONTEXT_WINDOW_TOKENS", 8192) or 8192))


def _index_manifest_path() -> Path:
    configured = str(getattr(config, "RAG_INDEX_MANIFEST_PATH", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    persist = Path(config.CHROMA_PERSIST_DIR).resolve()
    return (
        persist.parent / "production_manifest.json"
        if persist.name == "chroma"
        else persist / "production_manifest.json"
    )


def _load_index_manifest() -> PromotedIndexManifest:
    path = _index_manifest_path()
    if not path.is_file():
        raise RuntimeError(f"production retrieval index manifest is missing: {path}")
    manifest = PromotedIndexManifest.model_validate_json(path.read_bytes())
    expected_persist = (PROJECT_ROOT / manifest.persist_directory).resolve()
    if expected_persist != Path(config.CHROMA_PERSIST_DIR).resolve():
        raise RuntimeError("production retrieval manifest persist directory does not match configuration")
    if manifest.destination_collection != config.collection_name:
        raise RuntimeError("production retrieval manifest collection does not match configuration")
    if manifest.embedding_model != config.MODEL_EMBEDDING:
        raise RuntimeError("query embedding model does not match the production retrieval index")
    if manifest.embedding_distance != "cosine" or manifest.embedding_query_prefix:
        raise RuntimeError("production retrieval index must use cosine distance and an empty query prefix")
    return manifest


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieved evidence that was actually included in the answer context."""

    documents: list[Document]
    formatted_context: str
    has_results: bool
    assembly: AssembledContext
    retrieval_query: str
    term_resolution: CourseTermResolution | None


@dataclass(frozen=True)
class AnswerResult:
    """Grounded answer output."""

    answer: str
    sources: list[dict]
    has_context: bool


_RETRIEVAL_CACHE_LOCK = threading.RLock()
_RETRIEVAL_CACHE: OrderedDict[str, tuple[float, RetrievalResult]] = OrderedDict()


def _rag_retrieval_cache_enabled() -> bool:
    return bool(getattr(config, "RAG_RETRIEVAL_CACHE_ENABLED", True))


def _rag_retrieval_cache_ttl_seconds() -> float:
    return max(0.0, float(getattr(config, "RAG_RETRIEVAL_CACHE_TTL_SECONDS", 600.0) or 0.0))


def _rag_retrieval_cache_size() -> int:
    return max(0, int(getattr(config, "RAG_RETRIEVAL_CACHE_SIZE", 128) or 0))


def _retrieval_cache_key(
    question: str,
    *,
    candidate_depth: int,
    similarity_threshold: float | None,
    revision: str,
    term_resolution_query: str | None = None,
) -> str:
    """Bind cached retrievals to the complete vector/context policy identity."""
    threshold_key = "none" if similarity_threshold is None else f"{float(similarity_threshold):.6g}"
    # Term resolution depends on capitalization and token boundaries in the original input.
    raw = "|".join(
        [
            question,
            f"term_query={term_resolution_query if term_resolution_query is not None else question}",
            f"candidate_depth={candidate_depth}",
            f"threshold={threshold_key}",
            f"token_budget={_context_token_budget()}",
            f"tokenizer={_context_tokenizer_policy()}",
            f"dedup={_context_deduplication_mode()}",
            f"overflow={_context_overflow_policy()}",
            f"header={_context_header_policy()}",
            f"revision={revision}",
            f"collection={getattr(config, 'collection_name', getattr(config, 'COLLECTION_NAME', ''))}",
            f"persist={getattr(config, 'CHROMA_PERSIST_DIR', '')}",
            f"embedding_model={getattr(config, 'MODEL_EMBEDDING', '')}",
            f"embedding_base={getattr(config, 'BASE_URL', '')}",
            f"term_policy={COURSE_TERM_POLICY_VERSION}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clone_documents(documents: list[Document]) -> list[Document]:
    return [
        Document(
            page_content=str(getattr(doc, "page_content", "") or ""),
            metadata=dict(getattr(doc, "metadata", {}) or {}),
        )
        for doc in documents
    ]


def _clone_retrieval_result(result: RetrievalResult) -> RetrievalResult:
    assembly = clone_assembled_context(result.assembly)
    return RetrievalResult(
        documents=_clone_documents(assembly.documents),
        formatted_context=assembly.formatted_context or _NO_CONTEXT,
        has_results=bool(assembly.selected),
        assembly=assembly,
        retrieval_query=result.retrieval_query,
        term_resolution=result.term_resolution,
    )


def _get_cached_retrieval_result(
    question: str,
    *,
    candidate_depth: int,
    similarity_threshold: float | None,
    revision: str,
    term_resolution_query: str | None = None,
) -> RetrievalResult | None:
    maxsize = _rag_retrieval_cache_size()
    ttl = _rag_retrieval_cache_ttl_seconds()
    if not _rag_retrieval_cache_enabled() or maxsize <= 0 or ttl <= 0:
        return None

    key = _retrieval_cache_key(
        question,
        candidate_depth=candidate_depth,
        similarity_threshold=similarity_threshold,
        revision=revision,
        term_resolution_query=term_resolution_query,
    )
    now = time.monotonic()
    with _RETRIEVAL_CACHE_LOCK:
        cached = _RETRIEVAL_CACHE.get(key)
        if cached is None:
            _trace_rag_event(
                "rag.retrieve.cache_miss",
                reason="not_found",
                cache_size=len(_RETRIEVAL_CACHE),
                candidate_depth=candidate_depth,
            )
            return None
        created_at, result = cached
        if now - created_at > ttl:
            _RETRIEVAL_CACHE.pop(key, None)
            _trace_rag_event(
                "rag.retrieve.cache_miss",
                reason="expired",
                cache_size=len(_RETRIEVAL_CACHE),
                candidate_depth=candidate_depth,
            )
            return None
        _RETRIEVAL_CACHE.move_to_end(key)
        _trace_rag_event(
            "rag.retrieve.cache_hit",
            cache_size=len(_RETRIEVAL_CACHE),
            document_count=len(result.documents),
            context_tokens=result.assembly.used_tokens,
            candidate_depth=candidate_depth,
        )
        return _clone_retrieval_result(result)


def _store_cached_retrieval_result(
    question: str,
    result: RetrievalResult,
    *,
    candidate_depth: int,
    similarity_threshold: float | None,
    revision: str,
    term_resolution_query: str | None = None,
) -> None:
    maxsize = _rag_retrieval_cache_size()
    ttl = _rag_retrieval_cache_ttl_seconds()
    if not _rag_retrieval_cache_enabled() or maxsize <= 0 or ttl <= 0:
        return
    if not result.has_results:
        _trace_rag_event(
            "rag.retrieve.cache_skip",
            reason="empty_result",
            document_count=0,
            candidate_depth=candidate_depth,
        )
        return

    key = _retrieval_cache_key(
        question,
        candidate_depth=candidate_depth,
        similarity_threshold=similarity_threshold,
        revision=revision,
        term_resolution_query=term_resolution_query,
    )
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE[key] = (time.monotonic(), _clone_retrieval_result(result))
        _RETRIEVAL_CACHE.move_to_end(key)
        while len(_RETRIEVAL_CACHE) > maxsize:
            _RETRIEVAL_CACHE.popitem(last=False)
    _trace_rag_event(
        "rag.retrieve.cache_store",
        cache_size=len(_RETRIEVAL_CACHE),
        document_count=len(result.documents),
        context_tokens=result.assembly.used_tokens,
        candidate_depth=candidate_depth,
    )


def clear_rag_retrieval_cache() -> None:
    """Clear the in-process retrieval cache for tests or controlled cutovers."""
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE.clear()


class RAGService:
    """Course-term or raw-vector retrieval with one token-bounded assembly path."""

    def __init__(self) -> None:
        self.index_manifest = _load_index_manifest()
        self.embedding = OpenAIEmbeddings(
            **embedding_model_kwargs(timeout_seconds=retrieval_embedding_timeout_seconds())
        )
        self.vector_store_service = VectorStoreService(embedding=self.embedding)
        if self.vector_store_service.collection.count() != self.index_manifest.document_count:
            self.vector_store_service.close()
            raise RuntimeError("production retrieval collection count does not match its manifest")
        self.course_term_index = CourseTermIndex.from_collection_payload(self.vector_store_service.get_all_documents())
        self.prompt_template = build_rag_prompt_template()
        self.chat_model = get_rag_text_model()
        self._token_counter = load_token_counter(PROJECT_ROOT / "var" / "cache" / "tiktoken")

    def close(self) -> None:
        """Release the owned Chroma client."""
        self.vector_store_service.close()

    def _get_token_counter(self):
        counter = getattr(self, "_token_counter", None)
        if counter is None:
            counter = load_token_counter(PROJECT_ROOT / "var" / "cache" / "tiktoken")
            self._token_counter = counter
        return counter

    def _context_config(self, candidate_depth: int) -> ContextAssemblyConfig:
        return ContextAssemblyConfig(
            token_budget=_context_token_budget(),
            candidate_depth=candidate_depth,
            tokenizer_policy=_context_tokenizer_policy(),
            deduplication_mode=_context_deduplication_mode(),
            overflow_policy=_context_overflow_policy(),
            header_policy=_context_header_policy(),
        )

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        similarity_threshold: float | None = 1.0,
        *,
        term_resolution_query: str | None = None,
    ) -> RetrievalResult:
        """Retrieve evidence, resolving short terms from the current user query."""
        depth = max(1, int(top_k)) if top_k is not None else _candidate_depth()
        manifest = getattr(self, "index_manifest", None)
        manifest_revision = manifest.collection_revision if manifest is not None else "test"
        runtime_revision = read_kb_revision(config.collection_name, config.CHROMA_PERSIST_DIR)
        revision = f"{manifest_revision}:{runtime_revision}"
        cached_result = _get_cached_retrieval_result(
            question,
            candidate_depth=depth,
            similarity_threshold=similarity_threshold,
            revision=revision,
            term_resolution_query=term_resolution_query,
        )
        if cached_result is not None:
            _warn_large_rag_payload(
                cached_result.formatted_context,
                location="rag.retrieve.formatted_context",
                payload_type="rag_context",
                document_count=len(cached_result.documents),
                context_tokens=cached_result.assembly.used_tokens,
                candidate_depth=depth,
                cache_hit=True,
            )
            return cached_result

        candidates: list[RankedContextCandidate] = []
        term_lookup = self.course_term_index.lookup(term_resolution_query or question)
        retrieval_query = question
        term_resolution = None
        if term_lookup is not None:
            term_resolution = term_lookup.resolution
            retrieval_query = term_resolution.resolved_query
            _trace_rag_event(
                "rag.term_resolution",
                match_kind=term_resolution.match_kind.value,
                requested_term=term_resolution.requested_term,
                resolved_term=term_resolution.resolved_term,
                direct_document_count=len(term_lookup.documents),
                policy_version=term_resolution.policy_version,
            )
            for rank, document in enumerate(term_lookup.documents[:depth], start=1):
                candidates.append(
                    RankedContextCandidate(
                        document=document,
                        retrieval_rank=rank,
                        distance=0.0,
                        provenance=ChunkProvenance.from_document(document),
                    )
                )
        else:
            query_embedding = embed_query_cached(
                self.embedding,
                question,
                timeout_seconds=retrieval_embedding_timeout_seconds(),
            )
            results = self.vector_store_service.query(
                query_embeddings=[query_embedding],
                n_results=depth,
                include=["documents", "metadatas", "distances"],
            )
            documents = (results.get("documents") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]
            ids = (results.get("ids") or [[]])[0]
            if not (len(documents) == len(metadatas) == len(distances) == len(ids)):
                raise ValueError("Chroma returned inconsistent vector result columns")

            for rank, (chunk_id, text, metadata, distance) in enumerate(
                zip(ids, documents, metadatas, distances, strict=True),
                start=1,
            ):
                distance_value = float(distance)
                if similarity_threshold is not None and distance_value > similarity_threshold:
                    continue
                document_metadata = dict(metadata or {})
                document_metadata.setdefault("chunk_id", str(chunk_id))
                document = Document(page_content=str(text or ""), metadata=document_metadata)
                candidates.append(
                    RankedContextCandidate(
                        document=document,
                        retrieval_rank=rank,
                        distance=distance_value,
                        provenance=ChunkProvenance.from_document(document),
                    )
                )

        assembly = assemble_context(
            candidates,
            config=self._context_config(depth),
            token_counter=self._get_token_counter(),
        )
        formatted_context = assembly.formatted_context or _NO_CONTEXT
        selected_documents = assembly.documents
        _trace_rag_event(
            "rag.context_assembly",
            candidate_count=len(candidates),
            selected_document_count=len(selected_documents),
            candidate_depth=depth,
            used_tokens=assembly.used_tokens,
            token_budget=assembly.token_budget,
            duplicate_characters_removed=assembly.duplicate_characters_removed,
            skipped_fully_covered_count=assembly.skipped_fully_covered_count,
            stopped_on_overflow=assembly.stopped_on_overflow,
            overflow_retrieval_rank=assembly.overflow_retrieval_rank,
            policy_version=assembly.policy_version,
        )
        _warn_large_rag_payload(
            formatted_context,
            location="rag.retrieve.formatted_context",
            payload_type="rag_context",
            document_count=len(selected_documents),
            context_tokens=assembly.used_tokens,
            candidate_depth=depth,
        )

        result = RetrievalResult(
            documents=selected_documents,
            formatted_context=formatted_context,
            has_results=bool(selected_documents),
            assembly=assembly,
            retrieval_query=retrieval_query,
            term_resolution=term_resolution,
        )
        _store_cached_retrieval_result(
            question,
            result,
            candidate_depth=depth,
            similarity_threshold=similarity_threshold,
            revision=revision,
            term_resolution_query=term_resolution_query,
        )
        return result

    def _prepare_answer_prompt(self, question: str, context: str, *, mode: str) -> str:
        context_text = str(context or "")
        counter = self._get_token_counter()
        context_tokens = counter.count(context_text)
        if context_text != _NO_CONTEXT and context_tokens > _context_token_budget():
            raise ContextBudgetError(
                f"retrieved context uses {context_tokens} tokens, exceeding {_context_token_budget()}"
            )

        prompt = self.prompt_template.format(context=context_text, input=question)
        if config.CHAT_SYSTEM_SUFFIX:
            prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
        prompt_tokens = counter.count(prompt)
        answer_tokens = _answer_max_tokens()
        complete_tokens = prompt_tokens + answer_tokens
        window_tokens = _context_window_tokens()
        if complete_tokens > window_tokens:
            raise ContextBudgetError(
                "complete RAG prompt exceeds the serving context window: "
                f"prompt={prompt_tokens}, answer_reserve={answer_tokens}, window={window_tokens}"
            )
        _trace_rag_event(
            "rag.answer.prompt",
            mode=mode,
            prompt_tokens=prompt_tokens,
            context_tokens=context_tokens,
            answer_reserved_tokens=answer_tokens,
            context_window_tokens=window_tokens,
            tokenizer_policy=counter.policy_version,
        )
        _warn_large_rag_payload(
            prompt,
            location=f"rag.{mode}_answer.prompt",
            payload_type="llm_prompt",
            prompt_tokens=prompt_tokens,
            context_tokens=context_tokens,
        )
        return prompt

    def stream_answer_with_context(self, question: str, context: str) -> Iterator[str]:
        """Stream an answer after validating the complete production prompt."""
        prompt = self._prepare_answer_prompt(question, context, mode="stream")
        for chunk in self.chat_model.stream(prompt):
            content = getattr(chunk, "content", chunk)
            if isinstance(content, str) and content:
                yield content

    def answer_with_context(self, question: str, context: str, stream: bool = False) -> AnswerResult:
        """Generate a grounded answer after validating the complete prompt budget."""
        if stream:
            return self.stream_answer_with_context(question, context)

        prompt = self._prepare_answer_prompt(question, context, mode="sync")
        answer_msg = self.chat_model.invoke(prompt)
        answer_content = answer_msg.content if hasattr(answer_msg, "content") else str(answer_msg)
        _warn_large_rag_payload(
            answer_content,
            location="rag.answer.result",
            payload_type="rag_answer",
            has_context=context != _NO_CONTEXT,
        )
        return AnswerResult(answer=answer_content, sources=[], has_context=context != _NO_CONTEXT)


if __name__ == "__main__":
    service = RAGService()
    try:
        result = service.retrieve("什么是数据科学？")
        print(f"检索到 {len(result.documents)} 个文档")
        print(f"格式化上下文:\n{result.formatted_context[:500]}")
        if result.has_results:
            answer = service.answer_with_context("什么是数据科学？", result.formatted_context)
            print(f"\n回答:\n{answer.answer}")
    finally:
        service.close()
