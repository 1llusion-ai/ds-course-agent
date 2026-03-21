"""
知识库
"""
import os
import config_data as config
import hashlib
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from datetime import datetime

def check_md5(md5_str: str):
    """检查md5字符串是否存在，存在则返回True，不存在则返回False"""
    if not os.path.exists(config.md5_path):
        open(config.md5_path, "w", encoding="utf-8").close()  #如果文件不存在，则创建一个空文件
        return False
    else:
        for line in open(config.md5_path, "r", encoding="utf-8").readlines():
            line = line.strip()  #去除字符串前后的空格和回车
            if line == md5_str:
                return True
        return False



def save_md5(md5_str: str):
    """将传入的md5字符串，记录到文件保存"""
    with open(config.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")
    


def get_string_md5(input_str: str, encoding="utf-8") -> str:
    """将传入的字符串转为md5字符串"""
    #将字符串转换为bytes字节数组
    str_bytes = input_str.encode(encoding=encoding)
    #创建md5对象
    md5_obj = hashlib.md5()
    #更新md5对象
    md5_obj.update(str_bytes)
    #获取md5字符串
    md5_str = md5_obj.hexdigest()
    return md5_str


class KnowledgeBaseService(object):

    def __init__(self):

        os.makedirs(config.persist_directory, exist_ok=True)  #创建数据库本地存储文件夹路径
        self.chroma = Chroma(
            collection_name=config.collection_name,
            embedding_function=OpenAIEmbeddings(     #向量存储的嵌入函数
                model=config.MODEL_EMBEDDING, 
                api_key=config.API_KEY, 
                base_url=config.BASE_URL,  
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            ),
                    
            persist_directory=config.persist_directory, #数据库本地存储文件夹路径
        )      
        
        self.spilter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size, #文本分割的块大小
            chunk_overlap=config.chunk_overlap,  #文本分割的重叠大小
            separators=config.separators,  #文本分割的分隔符列表
            length_function=len,  #文本分割的长度函数，默认为len函数
        )     

    
    def upload_by_str(self, data: str, filename):
        """将传入的字符串向量化后存储到知识库中"""
        #先得到传入字符串的md5字符串
        md5_hex = get_string_md5(data)
        if not data or not data.strip():
            return "文件为空，跳过上传"
        if check_md5(md5_hex):
            print(f"文件 {filename} 已存在，跳过上传")
            return "文件已存在，跳过上传"
        if len(data) > config.max_split_char_number:
            #如果传入字符串的长度超过了文本分割的最大字符数，则先进行文本分割
            knowledge_chunks: list[str] = self.spilter.split_text(data)
        else:
            knowledge_chunks = [data]
        
        metadata = {
            "source": filename,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "admin"
        }  #为每个文本块添加元数据，记录来源文件名

        self.chroma.add_texts(
            knowledge_chunks, 
            metadatas=[metadata for _ in knowledge_chunks],  #为每个文本块添加元数据，记录来源文件名
        )

        save_md5(md5_hex)  #将传入字符串的md5字符串记录到文件保存，避免重复上传同一内容的文件
        return "文件上传成功！"
        

if __name__ == "__main__":
    service = KnowledgeBaseService()
    service.upload_by_str("这是一个测试文件的内容", filename="test_file.txt")
