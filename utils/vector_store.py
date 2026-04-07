import utils.config as config
from langchain_chroma import Chroma
class VectorStoreService(object):

    def __init__(self,embedding):
        self.embedding = embedding

        self.vector_store = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embedding,
            persist_directory=config.persist_directory,
        )


    def get_retriever(self):
        """获取向量存储的检索器,方便加入chain"""
        retriever = self.vector_store.as_retriever(search_kwargs={"k": config.similarity_top_k})
        return retriever
    
if __name__ == "__main__":
    from langchain_openai import OpenAIEmbeddings

    embedding = OpenAIEmbeddings(
        model=config.MODEL_EMBEDDING,
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        tiktoken_enabled=False,
        check_embedding_ctx_length=False,
    )

    retriever = VectorStoreService(embedding).get_retriever()
    res = retriever.invoke("我胸围96cm，性别男，应该穿什么尺码的衣服？")   #只需要字符串，input

    for i, doc in enumerate(res, 1):
        print(f"\n===== 检索结果 {i} =====")
        print("来源文件：", doc.metadata.get("source"))
        print("创建时间：", doc.metadata.get("create_time"))
        print("内容：")
        print(doc.page_content[:300])