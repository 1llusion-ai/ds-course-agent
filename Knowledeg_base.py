"""
知识库管理模块
支持课程资料的文本上传和向量化存储
"""
import os
import hashlib
from datetime import datetime
from typing import Optional

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config


def check_md5(md5_str: str) -> bool:
    """检查md5字符串是否存在"""
    if not os.path.exists(config.md5_path):
        open(config.md5_path, "w", encoding="utf-8").close()
        return False
    
    with open(config.md5_path, "r", encoding="utf-8") as f:
        for line in f.readlines():
            if line.strip() == md5_str:
                return True
    return False


def save_md5(md5_str: str):
    """保存md5字符串到记录文件"""
    with open(config.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")


def get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
    """计算字符串的MD5值"""
    str_bytes = input_str.encode(encoding=encoding)
    md5_obj = hashlib.md5()
    md5_obj.update(str_bytes)
    return md5_obj.hexdigest()


class KnowledgeBaseService(object):
    """知识库服务类"""

    def __init__(self, course_name: Optional[str] = None):
        self.course_name = course_name or config.COURSE_NAME
        
        os.makedirs(config.persist_directory, exist_ok=True)
        
        self.chroma = Chroma(
            collection_name=config.collection_name,
            embedding_function=OpenAIEmbeddings(
                model=config.MODEL_EMBEDDING,
                api_key=config.API_KEY,
                base_url=config.BASE_URL,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            ),
            persist_directory=config.persist_directory,
        )
        
        self.spilter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

    def upload_by_str(
        self,
        data: str,
        filename: str,
        course_source: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """
        将文本内容向量化后存储到知识库
        
        Args:
            data: 文本内容
            filename: 文件名
            course_source: 课程来源（如"第一章"、"课件"等）
            chapter: 章节信息
            
        Returns:
            str: 上传结果信息
        """
        md5_hex = get_string_md5(data)
        
        if not data or not data.strip():
            return "文件为空，跳过上传"
        
        if check_md5(md5_hex):
            print(f"文件 {filename} 已存在，跳过上传")
            return "文件已存在，跳过上传"
        
        if len(data) > config.max_split_char_number:
            knowledge_chunks: list[str] = self.spilter.split_text(data)
        else:
            knowledge_chunks = [data]
        
        metadata = {
            "source": filename,
            "course": self.course_name,
            "course_source": course_source or "课程资料",
            "chapter": chapter or "",
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "admin",
        }
        
        batch_size = 30
        total_chunks = len(knowledge_chunks)
        
        for i in range(0, total_chunks, batch_size):
            batch_chunks = knowledge_chunks[i:i + batch_size]
            batch_metadata = [metadata.copy() for _ in batch_chunks]
            
            self.chroma.add_texts(
                batch_chunks,
                metadatas=batch_metadata,
            )
            
            print(f"  进度: {min(i + batch_size, total_chunks)}/{total_chunks}")
        
        save_md5(md5_hex)
        return f"文件上传成功！共 {total_chunks} 个文本块"

    def get_collection_info(self) -> dict:
        """获取知识库信息"""
        try:
            count = self.chroma._collection.count()
            return {
                "collection_name": config.collection_name,
                "document_count": count,
                "course_name": self.course_name,
            }
        except Exception as e:
            return {
                "collection_name": config.collection_name,
                "document_count": 0,
                "course_name": self.course_name,
                "error": str(e),
            }


if __name__ == "__main__":
    service = KnowledgeBaseService()
    result = service.upload_by_str(
        "这是一个测试文件的内容",
        filename="test_file.txt",
        course_source="测试资料"
    )
    print(result)
    
    info = service.get_collection_info()
    print(f"知识库信息: {info}")
