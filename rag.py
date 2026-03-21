from hmac import new

from vector_store import VectorStoreService
from langchain_openai import OpenAIEmbeddings
import config_data as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import OllamaLLM
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from file_history_store import get_history

def print_prompt(prompt):
    print ("===== 传入模型的完整提示语 =====")
    print (prompt.to_string())
    print ("===============================")
    return prompt


class RAGService(object):
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
                ("system","并且我提供用户的对话历史记录，如下：\n"),
                MessagesPlaceholder("history"),
                ("user", "请回答用户提问:\n{input}"),
            ]
        )
        self.chat_model = OllamaLLM(model=config.MODEL_CHAT, base_url=config.BASE_URL_CHAT)
        self.chain = self.__get_chain()

    def __get_chain(self):
        """构建RAG链"""
        retriever = self.vector_store_service.get_retriever()

        def format_documents(docs:list[Document]):
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
                "context": RunnableLambda(lambda x: x["input"])  | retriever | format_documents
            } | RunnableLambda(build_prompt_inputs) | self.prompt_template | print_prompt |self.chat_model | StrOutputParser()
        )

        """
        RunnablePassthrough(): 直接传递输入，不进行任何修改。
        RunnableLambda(lambda x: x["input"]): 为了适应retriever需要的str格式，抽取出input字段作为输入。
        build_prompt_inputs函数：将输入的字典格式调整为prompt_template需要的格式，提取出input、context和history字段，并重新组织成新的字典。
        """


        conversation_chain = RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

        return conversation_chain

if __name__ == "__main__":
    session_config = {
        "configurable":{
            "session_id":"user_001"
        }
    }
    res = RAGService().chain.invoke({
        "input": "如何测量胸围？"},
         config=session_config)
    print("最终回答：", res)