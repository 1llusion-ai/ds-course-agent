"""
RAG 服务模块
提供检索和问答能力，支持被 Tool 和 Agent 调用
支持纯向量检索和BM25混合检索
"""
import logging
from typing import Optional
from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory

import ds_course_agent.shared.config as config
from ds_course_agent.shared.embeddings import embed_query_cached, embedding_model_kwargs
from ds_course_agent.shared.llm import get_rag_text_model
from ds_course_agent.shared.vector_store import VectorStoreService
from ds_course_agent.shared.history import get_history
from ds_course_agent.rag.hybrid_retriever import HybridRetriever

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


def _rag_context_trim_enabled() -> bool:
    return bool(getattr(config, "RAG_CONTEXT_TRIM_ENABLED", True))


def _rag_context_max_chars() -> int:
    return max(1, int(getattr(config, "RAG_CONTEXT_MAX_CHARS", 4500) or 4500))


def _rag_context_doc_max_chars() -> int:
    return max(1, int(getattr(config, "RAG_CONTEXT_DOC_MAX_CHARS", 1500) or 1500))


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


class RAGService(object):
    """RAG 服务类，提供检索和问答能力"""

    def __init__(self, use_hybrid: bool = True, use_rerank: Optional[bool] = None):
        """
        初始化RAG服务

        Args:
            use_hybrid: 是否使用BM25混合检索，默认为True
            use_rerank: 是否启用重排序，None时读取配置
        """
        self.use_hybrid = use_hybrid
        self.use_rerank = use_rerank if use_rerank is not None else config.ENABLE_RERANK

        # 初始化embedding
        self.embedding = OpenAIEmbeddings(**embedding_model_kwargs())

        # 初始化检索器
        if use_hybrid:
            logger.info("使用BM25混合检索")
            if self.use_rerank:
                logger.info("启用重排序")
            self.hybrid_retriever = HybridRetriever(
                k=config.similarity_top_k,
                use_rerank=self.use_rerank
            )
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
                ("system", "以我提供的参考材料为主，"
                 "简洁和专业的回答用户问题。参考资料：\n{context}。"),
                ("system", "并且我提供用户的对话历史记录，如下：\n"),
                MessagesPlaceholder("history"),
                ("user", "请回答用户提问:\n{input}"),
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
                "context": RunnableLambda(lambda x: x["input"]) | retriever | format_documents
            } | RunnableLambda(build_prompt_inputs) | self.prompt_template | self.chat_model | StrOutputParser()
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
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = 1.0,
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

        if self.use_hybrid and self.hybrid_retriever:
            # 使用BM25混合检索
            documents = self.hybrid_retriever.retrieve(question, top_k=k)
        else:
            # 使用纯向量检索
            from langchain_core.documents import Document

            # 获取查询的embedding
            query_embedding = embed_query_cached(self.embedding, question)

            # 直接查询ChromaDB获取文档和距离
            import chromadb
            client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
            collection = client.get_collection(config.collection_name)

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(k * 3, 10),  # 获取更多结果用于过滤
                include=["documents", "metadatas", "distances"]
            )

            # 过滤并构建文档列表
            documents = []
            if results['documents'] and results['documents'][0]:
                for doc_text, metadata, distance in zip(
                    results['documents'][0],
                    results['metadatas'][0],
                    results['distances'][0]
                ):
                    # 只保留相似度高于阈值的文档（距离小于阈值）
                    if similarity_threshold is None or distance <= similarity_threshold:
                        documents.append(Document(
                            page_content=doc_text,
                            metadata=metadata
                        ))
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

        return RetrievalResult(
            documents=documents,
            formatted_context=formatted_context,
            has_results=len(documents) > 0
        )

    def _normalize_document_metadata(self, doc: Document) -> dict:
        """Return prompt-facing metadata with stable textbook page labels."""
        from ds_course_agent.tools.course_rag import _get_absolute_page

        metadata = dict(getattr(doc, "metadata", {}) or {})
        # 优先使用已存储的 book_page，否则动态计算；避免把 chunk 内相对页码
        # 误展示给 LLM / UI。
        abs_page = metadata.get('book_page') or metadata.get('book_page_start') or _get_absolute_page(doc)
        if abs_page:
            metadata['page'] = int(abs_page)
            metadata['page_note'] = f"教材第{int(abs_page)}页"
        elif 'page' in metadata:
            del metadata['page']
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
            content = content_part[len(prefix):]
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
        prompt = self.prompt_template.format(
            context=context,
            history=[],
            input=question
        )
        if config.CHAT_SYSTEM_SUFFIX:
            prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
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

    def answer_with_context(
        self,
        question: str,
        context: str,
        stream: bool = False
    ) -> AnswerResult:
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

        prompt = self.prompt_template.format(
            context=context,
            history=[],
            input=question
        )
        if config.CHAT_SYSTEM_SUFFIX:
            prompt = f"{prompt}\n\n{config.CHAT_SYSTEM_SUFFIX}"
        _warn_large_rag_payload(
            prompt,
            location="rag.answer.prompt",
            payload_type="llm_prompt",
            context_chars=len(context or ""),
        )

        answer_msg = self.chat_model.invoke(prompt)

        # 提取纯字符串内容
        answer_content = answer_msg.content if hasattr(answer_msg, 'content') else str(answer_msg)
        _warn_large_rag_payload(
            answer_content,
            location="rag.answer.result",
            payload_type="rag_answer",
            has_context=context != "无相关资料",
        )

        return AnswerResult(
            answer=answer_content,
            sources=[],
            has_context=context != "无相关资料"
        )

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
