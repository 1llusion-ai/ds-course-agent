"""
混合检索模块 - 结合BM25稀疏检索和向量语义检索

实现方案:
1. BM25稀疏检索: 基于词频的精确匹配
2. 向量语义检索: 基于embedding的语义相似度
3. 融合排序: RR (Reciprocal Rank Fusion)
"""

import copy
import logging
import re
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Any

import chromadb
import numpy as np
from chromadb.errors import NotFoundError
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from rank_bm25 import BM25Okapi

import ds_course_agent.shared.config as config
from ds_course_agent.retrieval.timeouts import retrieval_embedding_timeout_seconds
from ds_course_agent.shared.embeddings import embed_query_cached, embedding_model_kwargs
from ds_course_agent.shared.kb_revision import read_kb_revision
from ds_course_agent.shared.query_trace import trace_span, trace_step

logger = logging.getLogger(__name__)

_COLLECTION_REFRESH_MAX_ATTEMPTS = 3
_COLLECTION_REFRESH_RETRY_DELAY_SECONDS = 0.05

_jieba = None


def _is_timeout_like_exception(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "timeout" in text or "timed out" in text


def _get_jieba():
    """Import jieba lazily while suppressing its setuptools deprecation noise.

    jieba currently imports ``pkg_resources`` in ``jieba._compat`` on import,
    which emits a third-party deprecation warning under newer setuptools.  The
    warning is not actionable for this project, so keep test output clean while
    preserving jieba-based tokenization.
    """
    global _jieba
    if _jieba is None:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API.*",
                category=UserWarning,
            )
            import jieba as jieba_module

        _jieba = jieba_module
    return _jieba


def _normalize_latin_tokens(text: str) -> str:
    """Make Latin tokens case-insensitive for retrieval, especially textbook acronyms."""
    return re.sub(r"[A-Za-z]{2,}", lambda match: match.group(0).upper(), text)


def reciprocal_rank_fusion(
    result_sets: list[list[tuple[int, float]]],
    rank_constant: int = 60,
) -> list[tuple[int, float]]:
    """Fuse ranked document indexes without depending on incomparable raw scores."""
    if rank_constant <= 0:
        raise ValueError("rank_constant must be positive")
    fusion_scores: dict[int, float] = {}
    for results in result_sets:
        ranked = sorted(results, key=lambda item: item[1], reverse=True)
        for rank, (doc_idx, _) in enumerate(ranked, start=1):
            fusion_scores[doc_idx] = fusion_scores.get(doc_idx, 0.0) + 1.0 / (rank_constant + rank)
    return sorted(fusion_scores.items(), key=lambda item: item[1], reverse=True)


class BM25Retriever:
    """BM25稀疏检索器"""

    def __init__(self):
        self.bm25: BM25Okapi | None = None
        self.documents: list[Document] = []
        self.tokenized_corpus: list[list[str]] = []

    def _tokenize(self, text: str) -> list[str]:
        """中文分词"""
        text = _normalize_latin_tokens(text)
        # 使用 jieba 分词；lazy import 避免第三方 pkg_resources 警告污染测试输出。
        tokens = list(_get_jieba().cut(text))
        # 过滤停用词和短词
        stopwords = {
            "的",
            "了",
            "在",
            "是",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "一个",
            "上",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "自己",
            "这",
        }
        return [t.strip() for t in tokens if len(t.strip()) > 1 and t.strip() not in stopwords]

    def add_documents(self, documents: list[Document]) -> None:
        """添加文档并构建BM25索引"""
        self.documents = documents
        self.tokenized_corpus = []
        self.bm25 = None

        for doc in documents:
            # 分词并添加到语料库
            tokens = self._tokenize(doc.page_content)
            self.tokenized_corpus.append(tokens)

        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """
        BM25检索

        Returns:
            List of (doc_index, score) tuples
        """
        if not self.bm25:
            return []

        # 分词查询
        tokenized_query = self._tokenize(query)

        # 获取BM25分数
        scores = self.bm25.get_scores(tokenized_query)

        # BM25's IDF is zero for a term that appears in every document (common
        # in tiny test or newly built corpora). Keep lexical overlap useful as
        # a fallback instead of returning an empty result set.
        if len(scores) and max(scores) <= 0 and tokenized_query:
            overlap = np.asarray(
                [sum(token in tokens for token in set(tokenized_query)) for tokens in self.tokenized_corpus],
                dtype=float,
            )
            if overlap.max(initial=0.0) > 0:
                scores = overlap

        # 获取Top-K
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((int(idx), float(scores[idx])))

        return results


@dataclass(frozen=True)
class _CorpusSnapshot:
    """Immutable references to one installed corpus generation."""

    collection: Any
    bm25_retriever: BM25Retriever
    documents: tuple[Document, ...]
    doc_text_to_index: dict[str, int]
    doc_prefix_to_index: dict[str, int]


class HybridRetriever:
    """混合检索器 - 融合BM25和向量检索"""

    def __init__(self, collection_name: str | None = None, k: int = 5, use_rerank: bool | None = None):
        """
        初始化混合检索器

        Args:
            collection_name: ChromaDB集合名称
            k: 返回结果数量
            use_rerank: 是否启用重排序，None则读取配置
        """
        self.collection_name = collection_name or config.collection_name
        self.k = k
        self.use_rerank = use_rerank if use_rerank is not None else config.ENABLE_RERANK
        if self.use_rerank:
            from ds_course_agent.retrieval.reranker import CrossEncoderReranker

            reranker = CrossEncoderReranker()
            if reranker.is_available:
                self.reranker = reranker
            else:
                logger.warning("Rerank requested but unavailable, fallback to hybrid only")
                self.reranker = None
                self.use_rerank = False
        else:
            self.reranker = None

        self.embedding = OpenAIEmbeddings(
            **embedding_model_kwargs(timeout_seconds=retrieval_embedding_timeout_seconds())
        )

        # 初始化BM25检索器
        self.bm25_retriever = BM25Retriever()
        self.chroma_client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        self.collection = self.chroma_client.get_collection(self.collection_name)
        self._doc_text_to_index: dict[str, int] = {}
        self._doc_prefix_to_index: dict[str, int] = {}

        # 连接ChromaDB并加载所有文档
        self._corpus_lock = threading.RLock()
        self._revision = read_kb_revision(self.collection_name)
        self._load_documents()

    def _clear_loaded_corpus(self) -> None:
        """Drop all collection-derived state after a refresh cannot acquire the collection."""
        self.collection = None
        self.bm25_retriever = BM25Retriever()
        self.documents = []
        self._doc_text_to_index = {}
        self._doc_prefix_to_index = {}

    def _refresh_for_revision(self, revision: str) -> None:
        """Refresh the collection and indexes with a bounded missing-collection policy."""
        for attempt in range(1, _COLLECTION_REFRESH_MAX_ATTEMPTS + 1):
            try:
                self.collection = self.chroma_client.get_collection(self.collection_name)
                self._load_documents()
            except NotFoundError as exc:
                if attempt < _COLLECTION_REFRESH_MAX_ATTEMPTS:
                    trace_step(
                        "retriever.collection_refresh_retry",
                        status="warning",
                        attempt=attempt,
                        max_attempts=_COLLECTION_REFRESH_MAX_ATTEMPTS,
                        collection=self.collection_name,
                        revision=revision,
                        error_type=type(exc).__name__,
                        error=str(exc)[:200],
                    )
                    logger.warning(
                        "Collection refresh retry %d/%d for %s at revision %s: %s",
                        attempt,
                        _COLLECTION_REFRESH_MAX_ATTEMPTS,
                        self.collection_name,
                        revision,
                        exc,
                    )
                    if _COLLECTION_REFRESH_RETRY_DELAY_SECONDS > 0:
                        time.sleep(_COLLECTION_REFRESH_RETRY_DELAY_SECONDS)
                    continue

                self._clear_loaded_corpus()
                self._revision = revision
                trace_step(
                    "retriever.collection_refresh_degraded",
                    status="warning",
                    reason="collection_not_found",
                    attempts=attempt,
                    collection=self.collection_name,
                    revision=revision,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
                logger.warning(
                    "Collection %s unavailable after %d refresh attempts at revision %s; "
                    "retrieval is degraded until the next revision",
                    self.collection_name,
                    attempt,
                    revision,
                )
                return

            self._revision = revision
            trace_step(
                "retriever.collection_refresh",
                status="ok",
                attempt=attempt,
                document_count=len(self.documents),
                collection=self.collection_name,
                revision=revision,
            )
            return

    def _load_documents(self):
        """从ChromaDB加载所有文档到BM25"""
        # 获取所有文档
        results = self.collection.get(include=["documents", "metadatas"])

        documents = []
        doc_text_to_index: dict[str, int] = {}
        doc_prefix_to_index: dict[str, int] = {}
        for idx, (text, meta) in enumerate(zip(results["documents"], results["metadatas"], strict=True)):
            documents.append(Document(page_content=text, metadata=meta))
            doc_text_to_index.setdefault(text, idx)
            doc_prefix_to_index.setdefault(text[:200], idx)

        # 添加到BM25索引
        bm25_retriever = BM25Retriever()
        bm25_retriever.add_documents(documents)
        self.bm25_retriever = bm25_retriever
        self.documents = documents
        self._doc_text_to_index = doc_text_to_index
        self._doc_prefix_to_index = doc_prefix_to_index

        logger.info("加载了 %d 个文档到BM25索引", len(documents))

    def _corpus_snapshot(self) -> _CorpusSnapshot:
        """Capture one corpus generation while the installation lock is held."""

        return _CorpusSnapshot(
            collection=self.collection,
            bm25_retriever=self.bm25_retriever,
            documents=tuple(self.documents),
            doc_text_to_index=self._doc_text_to_index,
            doc_prefix_to_index=self._doc_prefix_to_index,
        )

    def _vector_search(
        self,
        query: str,
        top_k: int,
        snapshot: _CorpusSnapshot,
    ) -> list[tuple[int, float]]:
        """向量语义检索 - 使用ChromaDB"""
        if not snapshot.documents or snapshot.collection is None:
            return []
        query = _normalize_latin_tokens(query)
        with trace_span("retriever.embedding_query"):
            query_embedding = embed_query_cached(
                self.embedding,
                query,
                timeout_seconds=retrieval_embedding_timeout_seconds(),
            )

        with trace_span("retriever.chroma_query"):
            results = snapshot.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k * 3, len(snapshot.documents)),
                include=["documents", "distances"],
            )

        # 通过内容匹配找到对应的文档索引
        results_list = []
        if results["documents"] and results["documents"][0]:
            for doc_text, distance in zip(results["documents"][0], results["distances"][0], strict=True):
                similarity = 1.0 - float(distance)
                idx = snapshot.doc_text_to_index.get(doc_text)
                if idx is None:
                    idx = snapshot.doc_prefix_to_index.get(doc_text[:200])
                if idx is not None:
                    results_list.append((idx, similarity))

        # 去重并排序
        seen = set()
        unique_results = []
        for idx, score in results_list:
            if idx not in seen:
                seen.add(idx)
                unique_results.append((idx, score))

        unique_results.sort(key=lambda x: x[1], reverse=True)
        return unique_results[:top_k]

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """Refresh atomically, then retrieve without serializing remote embedding calls."""

        with self._corpus_lock:
            revision = read_kb_revision(self.collection_name)
            if revision != self._revision:
                self._refresh_for_revision(revision)
            snapshot = self._corpus_snapshot()
        return self._retrieve_snapshot(query, snapshot, top_k)

    def _retrieve_snapshot(
        self,
        query: str,
        snapshot: _CorpusSnapshot,
        top_k: int | None = None,
    ) -> list[Document]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            排序后的文档列表
        """
        query = _normalize_latin_tokens(query)
        k = top_k or self.k
        rerank_top_k = config.RERANK_TOP_K

        # BM25检索
        with trace_span("retriever.bm25"):
            bm25_results = snapshot.bm25_retriever.retrieve(query, top_k=rerank_top_k)
        logger.debug("BM25返回 %d 个结果", len(bm25_results))

        # 向量检索。Embedding 服务不可用时，降级为 BM25-only，而不是让
        # 整个 RAG 检索失败/空结果。
        try:
            with trace_span("retriever.vector"):
                vector_results = self._vector_search(query, top_k=rerank_top_k, snapshot=snapshot)
        except Exception as exc:
            logger.warning("Vector retrieval failed; falling back to BM25-only: %s", exc)
            if _is_timeout_like_exception(exc):
                trace_step(
                    "rag.retrieve.vector_timeout_degraded",
                    status="warning",
                    timeout_seconds=retrieval_embedding_timeout_seconds(),
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
            else:
                trace_step(
                    "rag.retrieve.vector_degraded",
                    status="warning",
                    reason="embedding_or_vector_error",
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
            trace_step(
                "retriever.vector_fallback",
                status="error",
                reason="embedding_or_vector_error",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            vector_results = []
        logger.debug("Vector返回 %d 个结果", len(vector_results))

        # RRF融合
        with trace_span("retriever.rrf"):
            fused_results = reciprocal_rank_fusion([bm25_results, vector_results])
        logger.debug("融合后 %d 个结果", len(fused_results))

        # 获取候选文档（若启用rerank，取rerank_top_k；否则取k）
        candidate_count = rerank_top_k if (self.use_rerank and self.reranker) else k
        candidate_docs = []
        for doc_idx, fused_score in fused_results[:candidate_count]:
            if 0 <= doc_idx < len(snapshot.documents):
                doc = copy.copy(snapshot.documents[doc_idx])
                # 添加融合分数到返回文档副本，避免污染共享索引文档
                doc.metadata = dict(doc.metadata or {})
                doc.metadata["fused_score"] = fused_score
                candidate_docs.append(doc)

        # 重排序
        if self.use_rerank and self.reranker and candidate_docs:
            logger.debug("进入Rerank阶段，候选数=%d", len(candidate_docs))
            reranked = self.reranker.rerank(query, candidate_docs)
            documents = [doc for doc, score in reranked[:k]]
            for doc, score in reranked[:k]:
                doc.metadata["rerank_score"] = score
            logger.debug("Rerank后返回 Top-%d", k)
        else:
            documents = candidate_docs[:k]

        return documents


if __name__ == "__main__":
    # 测试混合检索
    print("测试混合检索器...")
    retriever = HybridRetriever(k=5)

    test_queries = ["什么是过拟合", "决策树算法", "LASSO回归", "第6章 监督学习"]

    for query in test_queries:
        print(f"\n{'=' * 50}")
        print(f"查询: {query}")
        print("=" * 50)

        results = retriever.retrieve(query)
        for i, doc in enumerate(results, 1):
            chapter = doc.metadata.get("chapter", "Unknown")
            score = doc.metadata.get("fused_score", 0)
            print(f"{i}. [{chapter}] 融合分数: {score:.4f}")
            print(f"   {doc.page_content[:100]}...")
