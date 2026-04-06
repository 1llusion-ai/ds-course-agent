"""
RAG 服务模块
提供检索和问答能力，支持被 Tool 和 Agent 调用
"""
from typing import Optional
from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings
from langchain_ollama import OllamaLLM
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory

import config_data as config
from vector_store import VectorStoreService
from file_history_store import get_history


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

    def __init__(self):
        self.vector_store_service = VectorStoreService(
            embedding=OpenAIEmbeddings(
                model=config.MODEL_EMBEDDING,
                api_key=config.API_KEY,
                base_url=config.BASE_URL,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            )
        )
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", "以我提供的参考材料为主，"
                 "简洁和专业的回答用户问题。参考资料：\n{context}。"),
                ("system", "并且我提供用户的对话历史记录，如下：\n"),
                MessagesPlaceholder("history"),
                ("user", "请回答用户提问:\n{input}"),
            ]
        )
        self.chat_model = OllamaLLM(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)
        self.chain = self._build_chain()

    def _build_chain(self):
        """构建 RAG 链（保留原有功能兼容）"""
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

    def retrieve(self, question: str, top_k: Optional[int] = None) -> RetrievalResult:
        """
        检索相关文档
        
        Args:
            question: 用户问题
            top_k: 返回文档数量，默认使用配置值
            
        Returns:
            RetrievalResult: 包含文档列表和格式化上下文
        """
        retriever = self.vector_store_service.get_retriever()
        if top_k is not None:
            retriever.search_kwargs["k"] = top_k
            
        documents = retriever.invoke(question)
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
        
        answer = self.chat_model.invoke(prompt)
        
        return AnswerResult(
            answer=answer,
            sources=[],
            has_context=context != "无相关资料"
        )

    def _format_documents(self, docs: list[Document]) -> str:
        """格式化文档列表为上下文字符串"""
        if not docs:
            return "无相关资料"
        formatted_docs = ""
        for doc in docs:
            formatted_docs += f"文档片段：{doc.page_content}\n文档元数据：{doc.metadata}\n\n"
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
