from __future__ import annotations

from typing import Any

import chromadb
from langchain_chroma import Chroma

import ds_course_agent.shared.config as config


class VectorStoreService:
    """Own the Chroma client and collection used by vector retrieval."""

    def __init__(self, embedding: Any) -> None:
        self.embedding = embedding

        client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        try:
            vector_store = Chroma(
                collection_name=config.collection_name,
                embedding_function=self.embedding,
                client=client,
            )
            collection = client.get_collection(config.collection_name)
        except Exception:
            client.close()
            raise

        self.client = client
        self.vector_store = vector_store
        self.collection = collection
        self._closed = False

    def get_retriever(self):
        """获取向量存储的检索器,方便加入chain"""
        retriever = self.vector_store.as_retriever(search_kwargs={"k": config.similarity_top_k})
        return retriever

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str],
    ) -> dict[str, Any]:
        """Query the owned collection without acquiring another client."""
        return self.collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            include=include,
        )

    def get_all_documents(self) -> dict[str, Any]:
        """Return all collection documents and metadata for exact term lookup."""

        return self.collection.get(include=["documents", "metadatas"])

    def close(self) -> None:
        """Release the owned Chroma client exactly once."""
        if self._closed:
            return
        self.client.close()
        self._closed = True


if __name__ == "__main__":
    from ds_course_agent.shared.embeddings import create_embedding_model

    embedding = create_embedding_model()

    retriever = VectorStoreService(embedding).get_retriever()
    res = retriever.invoke("我胸围96cm，性别男，应该穿什么尺码的衣服？")  # 只需要字符串，input

    for i, doc in enumerate(res, 1):
        print(f"\n===== 检索结果 {i} =====")
        print("来源文件：", doc.metadata.get("source"))
        print("创建时间：", doc.metadata.get("create_time"))
        print("内容：")
        print(doc.page_content[:300])
