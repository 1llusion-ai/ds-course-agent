"""
RAG 服务模块
提供检索和问答能力，支持被 Tool 和 Agent 调用
支持纯向量检索和BM25混合检索
"""
from typing import Optional
from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory

import utils.config as config
from utils.vector_store import VectorStoreService
from utils.history import get_history
from core.hybrid_retriever import HybridRetriever


# 根据配置选择LLM类
def get_chat_model():
    """获取聊天模型（支持本地Ollama和远程API）"""
    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.REMOTE_MODEL_NAME,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            temperature=0.7,
        )
    else:
        from langchain_ollama import OllamaLLM
        return OllamaLLM(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)


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

    def __init__(self, use_hybrid: bool = True):
        """
        初始化RAG服务

        Args:
            use_hybrid: 是否使用BM25混合检索，默认为True
        """
        self.use_hybrid = use_hybrid

        # 初始化embedding
        self.embedding = OpenAIEmbeddings(
            model=config.MODEL_EMBEDDING,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )

        # 初始化检索器
        if use_hybrid:
            print("[RAGService] 使用BM25混合检索")
            self.hybrid_retriever = HybridRetriever(k=config.similarity_top_k)
            self.vector_store_service = None
        else:
            print("[RAGService] 使用纯向量检索")
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
        self.chat_model = get_chat_model()
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

    def retrieve(self, question: str, top_k: Optional[int] = None, similarity_threshold: float = 0.85) -> RetrievalResult:
        """
        检索相关文档

        Args:
            question: 用户问题
            top_k: 返回文档数量，默认使用配置值
            similarity_threshold: 相似度阈值（仅用于纯向量检索）

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
            query_embedding = self.embedding.embed_query(question)

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
                    if distance <= similarity_threshold:
                        documents.append(Document(
                            page_content=doc_text,
                            metadata=metadata
                        ))
                    if len(documents) >= k:
                        break

        formatted_context = self._format_documents(documents)

        return RetrievalResult(
            documents=documents,
            formatted_context=formatted_context,
            has_results=len(documents) > 0
        )

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
        prompt = self.prompt_template.format(
            context=context,
            history=[],
            input=question
        )
        
        if stream:
            return self.chat_model.stream(prompt)
        
        answer_msg = self.chat_model.invoke(prompt)

        # 提取纯字符串内容
        answer_content = answer_msg.content if hasattr(answer_msg, 'content') else str(answer_msg)

        return AnswerResult(
            answer=answer_content,
            sources=[],
            has_context=context != "无相关资料"
        )

    def _format_documents(self, docs: list[Document]) -> str:
        """格式化文档列表为上下文字符串"""
        if not docs:
            return "无相关资料"
        formatted_docs = ""
        for doc in docs:
            # 构建包含绝对页码的元数据（删除相对页码避免混淆）
            from core.tools import _get_absolute_page
            metadata = dict(doc.metadata)
            abs_page = _get_absolute_page(doc)
            if abs_page:
                metadata['page'] = abs_page  # 用绝对页码覆盖相对页码
                metadata['page_note'] = f"教材第{abs_page}页"
            elif 'page' in metadata:
                del metadata['page']  # 删除无法转换的相对页码
            formatted_docs += f"文档片段：{doc.page_content}\n文档元数据：{metadata}\n\n"
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
