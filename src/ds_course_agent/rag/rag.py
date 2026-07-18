"""
RAG 服务模块
提供检索和问答能力，支持被 Tool 和 Agent 调用
支持纯向量检索和BM25混合检索
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory
from langchain_openai import OpenAIEmbeddings

import ds_course_agent.shared.config as config
from ds_course_agent.rag.hybrid_retriever import HybridRetriever
from ds_course_agent.shared.embeddings import embed_query_cached, embedding_model_kwargs
from ds_course_agent.shared.history import get_history
from ds_course_agent.shared.llm import get_rag_text_model
from ds_course_agent.shared.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


def _warn_large_rag_payload(payload: str, *, location: str, payload_type: str, **metadata) -> None:
    """Large RAG context/answer payload telemetry and artifact storage."""
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


def _trace_rag_context_trim(*, location: str, **metadata) -> None:
    """Emit best-effort trace for RAG context trimming."""
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step("rag.context_trim", location=location, **metadata)
    except Exception:
        logger.debug("Failed to emit RAG context trim trace at %s", location, exc_info=True)


def _trace_rag_answer_event(stage: str, **metadata) -> None:
    """Emit best-effort trace for answer prompt/cache/latency guards."""
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(stage, **metadata)
    except Exception:
        logger.debug("Failed to emit RAG answer trace event at %s", stage, exc_info=True)


def _trace_rag_retrieve_event(stage: str, **metadata) -> None:
    """Emit best-effort trace for retrieval cache/tail guards."""
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(stage, **metadata)
    except Exception:
        logger.debug("Failed to emit RAG retrieve trace event at %s", stage, exc_info=True)


def _rag_context_trim_enabled() -> bool:
    return bool(getattr(config, "RAG_CONTEXT_TRIM_ENABLED", True))


def _rag_context_max_chars() -> int:
    return max(1, int(getattr(config, "RAG_CONTEXT_MAX_CHARS", 3200) or 3200))


def _rag_context_doc_max_chars() -> int:
    return max(1, int(getattr(config, "RAG_CONTEXT_DOC_MAX_CHARS", 1000) or 1000))


def _rag_retrieval_embedding_timeout_seconds() -> float:
    return max(
        0.0,
        float(getattr(config, "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS", 2.0) or 0.0),
    )


def _truncate_text(value: str, max_chars: int) -> tuple[str, bool]:
    """Return ``value`` capped to ``max_chars`` without mutating caller data."""
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False

    marker = f"\n[片段已裁剪：原始 {len(text)} 字，保留前 {max_chars} 字]"
    keep = max(0, max_chars - len(marker))
    if keep <= 0:
        return text[:max_chars], True
    return f"{text[:keep].rstrip()}{marker}", True


@dataclass
class RetrievalResult:
    """检索结果"""

    documents: list[Document]
    formatted_context: str
    has_results: bool


@dataclass
class AnswerResult:
    """回答结果"""

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


def _normalize_retrieval_cache_question(question: str) -> str:
    return "".join(str(question or "").lower().split())


def _retrieval_cache_key(
    question: str,
    *,
    top_k: int,
    similarity_threshold: float | None,
    use_hybrid: bool,
) -> str:
    threshold_key = "none" if similarity_threshold is None else f"{float(similarity_threshold):.6g}"
    raw = "|".join(
        [
            _normalize_retrieval_cache_question(question),
            f"top_k={int(top_k)}",
            f"threshold={threshold_key}",
            f"hybrid={bool(use_hybrid)}",
            f"collection={getattr(config, 'collection_name', getattr(config, 'COLLECTION_NAME', ''))}",
            f"persist={getattr(config, 'CHROMA_PERSIST_DIR', '')}",
            f"trim={bool(getattr(config, 'RAG_CONTEXT_TRIM_ENABLED', True))}",
            f"max_chars={int(getattr(config, 'RAG_CONTEXT_MAX_CHARS', 3200) or 3200)}",
            f"doc_chars={int(getattr(config, 'RAG_CONTEXT_DOC_MAX_CHARS', 1000) or 1000)}",
            f"rerank={bool(getattr(config, 'ENABLE_RERANK', False))}",
            f"rerank_top_k={int(getattr(config, 'RERANK_TOP_K', 20) or 20)}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clone_documents(documents: list[Document]) -> list[Document]:
    return [
        Document(
            page_content=str(getattr(doc, "page_content", "") or ""),
            metadata=dict(getattr(doc, "metadata", {}) or {}),
        )
        for doc in (documents or [])
    ]


def _clone_retrieval_result(result: RetrievalResult) -> RetrievalResult:
    return RetrievalResult(
        documents=_clone_documents(result.documents),
        formatted_context=str(result.formatted_context or ""),
        has_results=bool(result.has_results),
    )


def _get_cached_retrieval_result(
    question: str,
    *,
    top_k: int,
    similarity_threshold: float | None,
    use_hybrid: bool,
) -> RetrievalResult | None:
    maxsize = _rag_retrieval_cache_size()
    ttl = _rag_retrieval_cache_ttl_seconds()
    if not _rag_retrieval_cache_enabled() or maxsize <= 0 or ttl <= 0:
        return None

    key = _retrieval_cache_key(
        question,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        use_hybrid=use_hybrid,
    )
    now = time.monotonic()
    with _RETRIEVAL_CACHE_LOCK:
        cached = _RETRIEVAL_CACHE.get(key)
        if cached is None:
            _trace_rag_retrieve_event(
                "rag.retrieve.cache_miss",
                reason="not_found",
                cache_size=len(_RETRIEVAL_CACHE),
                top_k=top_k,
            )
            return None
        created_at, result = cached
        if now - created_at > ttl:
            _RETRIEVAL_CACHE.pop(key, None)
            _trace_rag_retrieve_event(
                "rag.retrieve.cache_miss",
                reason="expired",
                cache_size=len(_RETRIEVAL_CACHE),
                top_k=top_k,
            )
            return None
        _RETRIEVAL_CACHE.move_to_end(key)
        _trace_rag_retrieve_event(
            "rag.retrieve.cache_hit",
            cache_size=len(_RETRIEVAL_CACHE),
            document_count=len(result.documents),
            context_chars=len(result.formatted_context or ""),
            top_k=top_k,
        )
        return _clone_retrieval_result(result)


def _store_cached_retrieval_result(
    question: str,
    result: RetrievalResult,
    *,
    top_k: int,
    similarity_threshold: float | None,
    use_hybrid: bool,
) -> None:
    maxsize = _rag_retrieval_cache_size()
    ttl = _rag_retrieval_cache_ttl_seconds()
    if not _rag_retrieval_cache_enabled() or maxsize <= 0 or ttl <= 0:
        return

    key = _retrieval_cache_key(
        question,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        use_hybrid=use_hybrid,
    )
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE[key] = (time.monotonic(), _clone_retrieval_result(result))
        _RETRIEVAL_CACHE.move_to_end(key)
        while len(_RETRIEVAL_CACHE) > maxsize:
            _RETRIEVAL_CACHE.popitem(last=False)
    _trace_rag_retrieve_event(
        "rag.retrieve.cache_store",
        cache_size=len(_RETRIEVAL_CACHE),
        document_count=len(result.documents),
        context_chars=len(result.formatted_context or ""),
        top_k=top_k,
    )


def clear_rag_retrieval_cache() -> None:
    """Clear in-process retrieval cache; useful for tests/benchmarks."""
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE.clear()


class RAGService:
    """RAG 服务类，提供检索和问答能力"""

    def __init__(self, use_hybrid: bool = True, use_rerank: bool | None = None):
        """
        初始化RAG服务

        Args:
            use_hybrid: 是否使用BM25混合检索，默认为True
            use_rerank: 是否启用重排序，None时读取配置
        """
        self.use_hybrid = use_hybrid
        self.use_rerank = use_rerank if use_rerank is not None else config.ENABLE_RERANK

        # 初始化embedding
        self.embedding = OpenAIEmbeddings(
            **embedding_model_kwargs(timeout_seconds=_rag_retrieval_embedding_timeout_seconds())
        )

        # 初始化检索器
        if use_hybrid:
            logger.info("使用BM25混合检索")
            if self.use_rerank:
                logger.info("启用重排序")
            self.hybrid_retriever = HybridRetriever(k=config.similarity_top_k, use_rerank=self.use_rerank)
            self.use_rerank = self.hybrid_retriever.use_rerank
            if use_rerank and not self.use_rerank:
                logger.warning("Rerank 不可用，已回退为纯 Hybrid")
            self.vector_store_service = None
        else:
            logger.info("使用纯向量检索")
            self.hybrid_retriever = None
            self.vector_store_service = VectorStoreService(embedding=self.embedding)

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是数据科学课程助教。只能依据参考材料回答；材料不足时请明确说明。"
                    "默认用3-6句或最多4个要点，先给结论，再给必要解释。"
                    "不要展开无关背景，不要编造教材外信息。参考材料：\n{context}",
                ),
                ("system", "用户的对话历史如下：\n"),
                MessagesPlaceholder("history"),
                ("user", "请简洁回答用户提问：\n{input}"),
            ]
        )
        self.chat_model = get_rag_text_model()
        self.chain = self._build_chain()

    def _build_chain(self):
        """构建 RAG 链（保留原有功能兼容）"""
        # 如果使用混合检索，不构建chain（chain不支持混合检索）
        if self.use_hybrid:
            return None

        retriever = self.vector_store_service.get_retriever()

        def format_documents(docs: list[Document]):
            if not docs:
                return "无相关资料"
            formatted_docs = ""
            for doc in docs:
                formatted_docs += f"文档片段：{doc.page_content}\n文档元数据：{doc.metadata}\n\n"
            return formatted_docs

        def build_prompt_inputs(value):
            new_value = {}
            new_value["input"] = value["input"]["input"]
            new_value["context"] = value["context"]
            new_value["history"] = value["input"]["history"]
            return new_value

        chain = (
            {
                "input": RunnablePassthrough(),
                "context": RunnableLambda(lambda x: x["input"]) | retriever | format_documents,
            }
            | RunnableLambda(build_prompt_inputs)
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )

        conversation_chain = RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

        return conversation_chain

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        similarity_threshold: float | None = 1.0,
    ) -> RetrievalResult:
        """
        检索相关文档

        Args:
            question: 用户问题
            top_k: 返回文档数量，默认使用配置值
            similarity_threshold: 相似度阈值（仅用于纯向量检索），为 None 时不过滤

        Returns:
            RetrievalResult: 包含文档列表和格式化上下文
        """
        k = top_k if top_k is not None else config.similarity_top_k
        cached_result = _get_cached_retrieval_result(
            question,
            top_k=k,
            similarity_threshold=similarity_threshold,
            use_hybrid=bool(self.use_hybrid and self.hybrid_retriever),
        )
        if cached_result is not None:
            _warn_large_rag_payload(
                cached_result.formatted_context,
                location="rag.retrieve.formatted_context",
                payload_type="rag_context",
                document_count=len(cached_result.documents),
                top_k=k,
                cache_hit=True,
            )
            return cached_result

        if self.use_hybrid and self.hybrid_retriever:
            # 使用BM25混合检索
            documents = self.hybrid_retriever.retrieve(question, top_k=k)
        else:
            # 使用纯向量检索
            from langchain_core.documents import Document

            # 获取查询的embedding
            query_embedding = embed_query_cached(
                self.embedding,
                question,
                timeout_seconds=_rag_retrieval_embedding_timeout_seconds(),
            )

            # 直接查询ChromaDB获取文档和距离
            import chromadb

            client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
            collection = client.get_collection(config.collection_name)

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(k * 3, 10),  # 获取更多结果用于过滤
                include=["documents", "metadatas", "distances"],
            )

            # 过滤并构建文档列表
            documents = []
            if results["documents"] and results["documents"][0]:
                for doc_text, metadata, distance in zip(
                    results["documents"][0], results["metadatas"][0], results["distances"][0], strict=True
                ):
                    # 只保留相似度高于阈值的文档（距离小于阈值）
                    if similarity_threshold is None or distance <= similarity_threshold:
                        documents.append(Document(page_content=doc_text, metadata=metadata))
                    if len(documents) >= k:
                        break

        formatted_context = self._format_documents(documents)
        _warn_large_rag_payload(
            formatted_context,
            location="rag.retrieve.formatted_context",
            payload_type="rag_context",
            document_count=len(documents),
            top_k=k,
        )

        result = RetrievalResult(
            documents=documents, formatted_context=formatted_context, has_results=len(documents) > 0
        )
        _store_cached_retrieval_result(
            question,
            result,
            top_k=k,
            similarity_threshold=similarity_threshold,
            use_hybrid=bool(self.use_hybrid and self.hybrid_retriever),
        )
        return result

    def _normalize_document_metadata(self, doc: Document) -> dict:
        """Return prompt-facing metadata with stable textbook page labels."""
        from ds_course_agent.tools.course_rag import _get_absolute_page

        metadata = dict(getattr(doc, "metadata", {}) or {})
        # 优先使用已存储的 book_page，否则动态计算；避免把 chunk 内相对页码
        # 误展示给 LLM / UI。
        abs_page = metadata.get("book_page") or metadata.get("book_page_start") or _get_absolute_page(doc)
        if abs_page:
            metadata["page"] = int(abs_page)
            metadata["page_note"] = f"教材第{int(abs_page)}页"
        elif "page" in metadata:
            del metadata["page"]
        return metadata

    def _format_one_document(
        self,
        doc: Document,
        *,
        max_content_chars: int | None = None,
    ) -> tuple[str, bool]:
        """Format one retrieved document while preserving source metadata."""
        content = str(getattr(doc, "page_content", "") or "")
        trimmed = False
        if _rag_context_trim_enabled() and max_content_chars is not None:
            content, trimmed = _truncate_text(content, max_content_chars)
        metadata = self._normalize_document_metadata(doc)
        return f"文档片段：{content}\n文档元数据：{metadata}\n\n", trimmed

    def _fit_document_to_remaining_budget(
        self,
        doc: Document,
        *,
        remaining_chars: int,
    ) -> tuple[str, bool]:
        """Fit a document block into the remaining total context budget.

        The metadata suffix is treated as higher priority than the body because
        it is what lets the answer cite the retrieved material correctly.  If a
        caller configures an unrealistically tiny budget we may omit the body,
        but we still try to keep the source metadata visible.
        """
        if remaining_chars <= 0:
            return "", True

        metadata = self._normalize_document_metadata(doc)
        content = str(getattr(doc, "page_content", "") or "")
        prefix = "文档片段："
        suffix = f"\n文档元数据：{metadata}\n\n"
        full = f"{prefix}{content}{suffix}"
        if len(full) <= remaining_chars:
            return full, False

        marker = f"\n[片段已按总上下文预算裁剪：原始 {len(content)} 字]"
        available_for_content = remaining_chars - len(prefix) - len(suffix) - len(marker)
        if available_for_content > 0:
            body = content[:available_for_content].rstrip()
            return f"{prefix}{body}{marker}{suffix}", True

        # Budget is too small to guarantee both a body and the full metadata.
        # Drop this lower-ranked document instead of cutting source metadata in
        # half; source/citation fidelity is more important than squeezing in a
        # broken partial block.
        minimal = f"{prefix}[片段因上下文预算省略]{suffix}"
        if len(minimal) <= remaining_chars:
            return minimal, True
        return "", True

    def _trim_context_text_for_prompt(self, context: str, *, location: str) -> str:
        """Final guard for externally supplied RAG contexts.

        ``retrieve()`` already formats and trims its own context.  This guard is
        intentionally kept because tests and some integrations may call
        ``answer_with_context`` directly with a large raw string.
        """
        text = str(context or "")
        if not _rag_context_trim_enabled() or text == "无相关资料":
            return text

        max_chars = _rag_context_max_chars()
        if len(text) <= max_chars:
            return text

        original_chars = len(text)
        blocks = [block for block in text.split("\n\n") if block]
        kept: list[str] = []
        used = 0
        for block in blocks:
            candidate = f"{block}\n\n"
            if used + len(candidate) <= max_chars:
                kept.append(candidate)
                used += len(candidate)
                continue
            remaining = max_chars - used
            if remaining > 0:
                fitted = self._fit_formatted_context_block(block, remaining_chars=remaining)
                if fitted:
                    kept.append(fitted)
            break

        trimmed = "".join(kept).rstrip()
        if not trimmed:
            trimmed = text[:max_chars].rstrip()

        _trace_rag_context_trim(
            location=location,
            original_chars=original_chars,
            trimmed_chars=len(trimmed),
            max_chars=max_chars,
            mode="prompt_guard",
        )
        return trimmed

    def _fit_formatted_context_block(self, block: str, *, remaining_chars: int) -> str:
        """Fit a pre-formatted context block without cutting metadata in half."""
        if remaining_chars <= 0:
            return ""

        candidate = f"{block}\n\n"
        if len(candidate) <= remaining_chars:
            return candidate

        delimiter = "\n文档元数据："
        prefix = "文档片段："
        if block.startswith(prefix) and delimiter in block:
            content_part, metadata_part = block.split(delimiter, 1)
            content = content_part[len(prefix) :]
            suffix = f"{delimiter}{metadata_part}\n\n"
            marker = f"\n[片段已按总上下文预算裁剪：原始 {len(content)} 字]"
            available_for_content = remaining_chars - len(prefix) - len(suffix) - len(marker)
            if available_for_content > 0:
                body = content[:available_for_content].rstrip()
                return f"{prefix}{body}{marker}{suffix}"
            minimal = f"{prefix}[片段因上下文预算省略]{suffix}"
            if len(minimal) <= remaining_chars:
                return minimal
            return ""

        truncated, _ = _truncate_text(candidate, remaining_chars)
        return truncated[:remaining_chars]

    def stream_answer_with_context(self, question: str, context: str):
        """Stream an answer grounded in the retrieved context."""
        context = self._trim_context_text_for_prompt(context, location="rag.stream_answer.context")
        prompt = self.prompt_template.format(context=context, history=[], input=question)
        if config.CHAT_SYSTEM_SUFFIX:
            prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
        _trace_rag_answer_event(
            "rag.answer.prompt_compact",
            mode="stream",
            prompt_chars=len(prompt),
            context_chars=len(context or ""),
            max_tokens=int(getattr(config, "RAG_ANSWER_MAX_TOKENS", 384) or 384),
        )
        _warn_large_rag_payload(
            prompt,
            location="rag.stream_answer.prompt",
            payload_type="llm_prompt",
            context_chars=len(context or ""),
        )

        for chunk in self.chat_model.stream(prompt):
            content = getattr(chunk, "content", chunk)
            if isinstance(content, str) and content:
                yield content

    def answer_with_context(self, question: str, context: str, stream: bool = False) -> AnswerResult:
        """
        基于上下文回答问题

        Args:
            question: 用户问题
            context: 检索到的上下文
            stream: 是否流式输出

        Returns:
            AnswerResult: 包含回答和来源信息
        """
        context = self._trim_context_text_for_prompt(context, location="rag.answer.context")
        if stream:
            return self.stream_answer_with_context(question, context)

        prompt = self.prompt_template.format(context=context, history=[], input=question)
        if config.CHAT_SYSTEM_SUFFIX:
            prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
        _trace_rag_answer_event(
            "rag.answer.prompt_compact",
            mode="sync",
            prompt_chars=len(prompt),
            context_chars=len(context or ""),
            max_tokens=int(getattr(config, "RAG_ANSWER_MAX_TOKENS", 384) or 384),
        )
        _warn_large_rag_payload(
            prompt,
            location="rag.answer.prompt",
            payload_type="llm_prompt",
            context_chars=len(context or ""),
        )

        answer_msg = self.chat_model.invoke(prompt)

        # 提取纯字符串内容
        answer_content = answer_msg.content if hasattr(answer_msg, "content") else str(answer_msg)
        _warn_large_rag_payload(
            answer_content,
            location="rag.answer.result",
            payload_type="rag_answer",
            has_context=context != "无相关资料",
        )

        return AnswerResult(answer=answer_content, sources=[], has_context=context != "无相关资料")

    def _format_documents(self, docs: list[Document]) -> str:
        """格式化文档列表为上下文字符串"""
        if not docs:
            return "无相关资料"

        if not _rag_context_trim_enabled():
            return "".join(self._format_one_document(doc, max_content_chars=None)[0] for doc in docs)

        max_chars = _rag_context_max_chars()
        doc_max_chars = _rag_context_doc_max_chars()
        untrimmed_docs = [self._format_one_document(doc, max_content_chars=None)[0] for doc in docs]
        original_chars = sum(len(item) for item in untrimmed_docs)

        formatted_parts: list[str] = []
        used_chars = 0
        trimmed_docs = 0
        dropped_docs = 0

        for doc in docs:
            doc_text, doc_trimmed = self._format_one_document(doc, max_content_chars=doc_max_chars)
            if used_chars + len(doc_text) <= max_chars:
                formatted_parts.append(doc_text)
                used_chars += len(doc_text)
                if doc_trimmed:
                    trimmed_docs += 1
                continue

            remaining = max_chars - used_chars
            fitted, fitted_trimmed = self._fit_document_to_remaining_budget(
                doc,
                remaining_chars=remaining,
            )
            if fitted:
                formatted_parts.append(fitted)
                used_chars += len(fitted)
                if fitted_trimmed or doc_trimmed:
                    trimmed_docs += 1
            else:
                dropped_docs += 1

            # Once a document had to be fitted/dropped, later lower-ranked
            # documents are outside the current prompt budget.
            dropped_docs += max(0, len(docs) - (len(formatted_parts) + dropped_docs))
            break

        formatted_docs = "".join(formatted_parts).rstrip()
        if not formatted_docs:
            formatted_docs = "无相关资料"

        if trimmed_docs or dropped_docs or len(formatted_docs) < original_chars:
            _trace_rag_context_trim(
                location="rag.format_documents",
                original_chars=original_chars,
                trimmed_chars=len(formatted_docs),
                max_chars=max_chars,
                doc_max_chars=doc_max_chars,
                document_count=len(docs),
                trimmed_docs=trimmed_docs,
                dropped_docs=dropped_docs,
                mode="retrieve_format",
            )

        return formatted_docs


def print_prompt(prompt):
    print("===== 传入模型的完整提示语 =====")
    print(prompt.to_string())
    print("===============================")
    return prompt


if __name__ == "__main__":
    service = RAGService()

    result = service.retrieve("什么是数据科学？")
    print(f"检索到 {len(result.documents)} 个文档")
    print(f"格式化上下文:\n{result.formatted_context[:500]}")

    if result.has_results:
        answer = service.answer_with_context("什么是数据科学？", result.formatted_context)
        print(f"\n回答:\n{answer.answer}")
