md5_path = "F:\\Projects\\HelloAgent\\RAGAgent_Learning\\RAG_Project\\md5.text"

#Chroma
collection_name = "rag_knowledge_base"  #向量存储的集合名称
persist_directory = "F:\\Projects\\HelloAgent\\RAGAgent_Learning\\RAG_Project\\chroma_db"  #数据库本地存储文件夹路径

#文本分割器
API_KEY = "sk-msdwosvlpoyptcxnwshjzyclkgrvujevfhoawirgvxfmzwzf"
BASE_URL = "https://api.siliconflow.cn/v1"
MODEL_EMBEDDING = "BAAI/bge-large-zh-v1.5"

#spliter
chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", " ", "", ".", "?", "!", ",", "，", "。", "？", "！"]
max_split_char_number = 1000

#retriever
similarity_top_k = 1

#Chatmodel
MODEL_CHAT = "qwen3:8b"
BASE_URL_CHAT = "http://localhost:11434"

#history store
storage_path = "F:\\Projects\\HelloAgent\\RAGAgent_Learning\\RAG_Project\\chat_history"  # 会话历史存储路径

#session_config
session_config = {
        "configurable":{
            "session_id":"user_001"
        }
    }