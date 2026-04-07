"""
混合检索模块 - 结合BM25稀疏检索和向量语义检索

实现方案:
1. BM25稀疏检索: 基于词频的精确匹配
2. 向量语义检索: 基于embedding的语义相似度
3. 融合排序: RR (Reciprocal Rank Fusion)
"""
import re
import jieba
import numpy as np
from typing import List, Optional
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
import chromadb

import utils.config as config


@dataclass
class RetrievalResult:
    """检索结果"""
    document: Document
    bm25_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0


class BM25Retriever:
    """BM25稀疏检索器"""

    def __init__(self):
        self.bm25: Optional[BM25Okapi] = None
        self.documents: List[Document] = []
        self.tokenized_corpus: List[List[str]] = []

    def _tokenize(self, text: str) -> List[str]:
        """中文分词"""
        # 使用jieba分词
        tokens = list(jieba.cut(text))
        # 过滤停用词和短词
        stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
        return [t.strip() for t in tokens if len(t.strip()) > 1 and t.strip() not in stopwords]

    def add_documents(self, documents: List[Document]):
        """添加文档并构建BM25索引"""
        self.documents = documents
        self.tokenized_corpus = []

        for doc in documents:
            # 分词并添加到语料库
            tokens = self._tokenize(doc.page_content)
            self.tokenized_corpus.append(tokens)

        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query: str, top_k: int = 10) -> List[tuple[int, float]]:
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

        # 获取Top-K
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((int(idx), float(scores[idx])))

        return results


class HybridRetriever:
    """混合检索器 - 融合BM25和向量检索"""

    def __init__(self, collection_name: Optional[str] = None, k: int = 5):
        """
        初始化混合检索器

        Args:
            collection_name: ChromaDB集合名称
            k: 返回结果数量
        """
        self.collection_name = collection_name or config.collection_name
        self.k = k
        self.embedding = OpenAIEmbeddings(
            model=config.MODEL_EMBEDDING,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )

        # 初始化BM25检索器
        self.bm25_retriever = BM25Retriever()

        # 连接ChromaDB并加载所有文档
        self._load_documents()

    def _load_documents(self):
        """从ChromaDB加载所有文档到BM25"""
        client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        collection = client.get_collection(self.collection_name)

        # 获取所有文档
        results = collection.get(include=["documents", "metadatas"])

        documents = []
        for text, meta in zip(results['documents'], results['metadatas']):
            documents.append(Document(page_content=text, metadata=meta))

        # 添加到BM25索引
        self.bm25_retriever.add_documents(documents)
        self.documents = documents

        print(f"[HybridRetriever] 加载了 {len(documents)} 个文档到BM25索引")

    def _vector_search(self, query: str, top_k: int = 10) -> List[tuple[int, float]]:
        """向量语义检索 - 使用ChromaDB"""
        query_embedding = self.embedding.embed_query(query)

        client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        collection = client.get_collection(self.collection_name)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k * 3, len(self.documents)),
            include=["documents", "distances"]
        )

        # 通过内容匹配找到对应的文档索引
        results_list = []
        if results['documents'] and results['documents'][0]:
            for doc_text, distance in zip(results['documents'][0], results['distances'][0]):
                # 在已加载的文档中查找匹配的文档
                similarity = 1.0 - float(distance)
                for idx, doc in enumerate(self.documents):
                    if doc.page_content == doc_text or doc.page_content[:200] == doc_text[:200]:
                        results_list.append((idx, similarity))
                        break

        # 去重并排序
        seen = set()
        unique_results = []
        for idx, score in results_list:
            if idx not in seen:
                seen.add(idx)
                unique_results.append((idx, score))

        unique_results.sort(key=lambda x: x[1], reverse=True)
        return unique_results[:top_k]

    def _reciprocal_rank_fusion(
        self,
        bm25_results: List[tuple[int, float]],
        vector_results: List[tuple[int, float]],
        k: int = 60
    ) -> List[tuple[int, float]]:
        """
        RRF (Reciprocal Rank Fusion) 融合排序

        score = Σ(1 / (k + rank))

        Args:
            bm25_results: [(doc_idx, score), ...]
            vector_results: [(doc_idx, score), ...]
            k: RRF常数，通常取60

        Returns:
            [(doc_idx, fused_score), ...] 按分数降序排列
        """
        fusion_scores = {}

        # BM25结果 - 按分数排序得到排名
        bm25_ranked = sorted(bm25_results, key=lambda x: x[1], reverse=True)
        for rank, (doc_idx, _) in enumerate(bm25_ranked, start=1):
            fusion_scores[doc_idx] = fusion_scores.get(doc_idx, 0) + 1.0 / (k + rank)

        # 向量结果 - 按分数排序得到排名
        vector_ranked = sorted(vector_results, key=lambda x: x[1], reverse=True)
        for rank, (doc_idx, _) in enumerate(vector_ranked, start=1):
            fusion_scores[doc_idx] = fusion_scores.get(doc_idx, 0) + 1.0 / (k + rank)

        # 按融合分数排序
        sorted_results = sorted(fusion_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Document]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            排序后的文档列表
        """
        k = top_k or self.k

        # BM25检索
        bm25_results = self.bm25_retriever.retrieve(query, top_k=20)
        print(f"[Hybrid] BM25返回 {len(bm25_results)} 个结果")

        # 向量检索
        vector_results = self._vector_search(query, top_k=20)
        print(f"[Hybrid] Vector返回 {len(vector_results)} 个结果")

        # RRF融合
        fused_results = self._reciprocal_rank_fusion(bm25_results, vector_results)
        print(f"[Hybrid] 融合后 {len(fused_results)} 个结果")

        # 获取Top-K文档
        documents = []
        for doc_idx, fused_score in fused_results[:k]:
            if 0 <= doc_idx < len(self.documents):
                doc = self.documents[doc_idx]
                # 添加融合分数到元数据
                doc.metadata['fused_score'] = fused_score
                documents.append(doc)

        return documents


if __name__ == "__main__":
    # 测试混合检索
    print("测试混合检索器...")
    retriever = HybridRetriever(k=5)

    test_queries = [
        "什么是过拟合",
        "决策树算法",
        "LASSO回归",
        "第6章 监督学习"
    ]

    for query in test_queries:
        print(f"\n{'='*50}")
        print(f"查询: {query}")
        print('='*50)

        results = retriever.retrieve(query)
        for i, doc in enumerate(results, 1):
            chapter = doc.metadata.get('chapter', 'Unknown')
            score = doc.metadata.get('fused_score', 0)
            print(f"{i}. [{chapter}] 融合分数: {score:.4f}")
            print(f"   {doc.page_content[:100]}...")
