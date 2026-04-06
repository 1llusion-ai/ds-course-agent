"""
课程知识库向量存储模块

批量写入 Chroma，支持重试与幂等
建立课程专用 collection

Metadata 扩展：
- chunk_type: struct/semantic/shadow
- heading_path: 标题路径
- page_start/page_end: 页码范围
- source_pages: 源页码列表
- parser_source: 解析器来源
"""
import os
import re
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class IngestResult:
    """入库结果"""
    source_file: str
    total_chunks: int
    success_count: int
    skip_count: int
    error_count: int
    filtered_count: int = 0  # 过滤的非语义块数量
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


@dataclass
class KBStatus:
    """知识库状态"""
    collection_name: str
    course_name: str
    document_count: int
    last_updated: Optional[str]
    sources: list[str]


def sanitize_collection_name(name: str, fallback_prefix: str = "course") -> str:
    """
    将名称转换为合法的 ChromaDB collection 名称
    
    ChromaDB collection 名称规则：
    - 只能包含 [a-zA-Z0-9._-]
    - 长度必须在 3-512 之间
    - 首尾必须是字母或数字
    """
    if not name:
        return f"{fallback_prefix}_default"
    
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    sanitized = sanitized.strip('._-')
    
    if len(sanitized) < 3:
        hash_suffix = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
        sanitized = f"{fallback_prefix}_{hash_suffix}"
    
    if len(sanitized) > 512:
        sanitized = sanitized[:512]
        sanitized = sanitized.rstrip('._-')
    
    if not sanitized[0].isalnum():
        sanitized = 'c' + sanitized[1:]
    if not sanitized[-1].isalnum():
        sanitized = sanitized[:-1] + '0'
    
    if len(sanitized) < 3:
        sanitized = f"{fallback_prefix}_default"
    
    return sanitized


class CourseKnowledgeBase:
    """课程知识库管理"""
    
    def __init__(self, course_name: Optional[str] = None):
        import config_data as config
        from langchain_chroma import Chroma
        from langchain_openai import OpenAIEmbeddings
        
        self._chroma_cls = Chroma
        self._config = config
        
        self.course_name = course_name or config.COURSE_NAME
        
        if config.COURSE_COLLECTION_NAME:
            self.collection_name = config.COURSE_COLLECTION_NAME
        else:
            sanitized = sanitize_collection_name(self.course_name)
            if sanitized.startswith("course_"):
                self.collection_name = sanitized
            else:
                self.collection_name = f"course_{sanitized}"
        
        os.makedirs(config.CHROMA_PERSIST_DIR, exist_ok=True)
        
        self.embedding = OpenAIEmbeddings(
            model=config.MODEL_EMBEDDING,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            tiktoken_enabled=False,
            check_embedding_ctx_length=False,
        )
        
        self.vector_store = self._chroma_cls(
            collection_name=self.collection_name,
            embedding_function=self.embedding,
            persist_directory=config.CHROMA_PERSIST_DIR,
        )
        
        self.hash_file = Path(config.CHROMA_PERSIST_DIR) / f"{self.collection_name}_hashes.json"
        self.hashes = self._load_hashes()
    
    def _load_hashes(self) -> dict[str, str]:
        """加载已处理的分块哈希"""
        if self.hash_file.exists():
            try:
                with open(self.hash_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _save_hashes(self):
        """保存哈希记录"""
        with open(self.hash_file, 'w', encoding='utf-8') as f:
            json.dump(self.hashes, f, ensure_ascii=False, indent=2)
    
    def _compute_chunk_hash(self, chunk) -> str:
        """计算分块哈希"""
        # 兼容 V1 和 V2 结构
        if hasattr(chunk.metadata, 'source_file'):
            source = chunk.metadata.source_file  # V2
        else:
            source = chunk.metadata.source  # V1
        content = f"{chunk.content}:{source}:{chunk.metadata.chunk_type}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _build_metadata(self, chunk) -> dict:
        """
        构建扩展的 metadata
        兼容 V1 和 V2 结构
        """
        metadata = chunk.metadata

        # 检测 V1 还是 V2 结构
        is_v2 = hasattr(metadata, 'chapter_number')  # V2 特有属性

        if is_v2:
            # V2 结构 (course_chunker_v2)
            source_pages_json = json.dumps(metadata.source_pages) if metadata.source_pages else "[]"
            return {
                "course": self.course_name,
                "source": metadata.source_file,
                "chunk_type": metadata.chunk_type,
                "heading_path": '',
                "chapter": metadata.chapter,
                "chapter_no": metadata.chapter_number,
                "section": metadata.section,
                "section_no": metadata.section_number,
                "subsection": metadata.subsection,
                "subsection_no": metadata.subsection_number,
                "page": metadata.source_pages[0] if metadata.source_pages else 0,
                "page_start": metadata.source_pages[0] if metadata.source_pages else 0,
                "page_end": metadata.source_pages[-1] if metadata.source_pages else 0,
                "source_pages": source_pages_json,
                "parser_source": 'marker_v2',
                "chunk_id": f"{metadata.source_file}_{hash(chunk.content) % 1000000:06d}",
                "char_count": len(chunk.content),
                "position": 0,
                "ingest_time": datetime.now().isoformat(),
            }
        else:
            # V1 结构 (旧版 course_chunker)
            source_pages_json = json.dumps(metadata.source_pages) if hasattr(metadata, 'source_pages') else "[]"
            return {
                "course": self.course_name,
                "source": metadata.source,
                "chunk_type": getattr(metadata, 'chunk_type', 'struct'),
                "heading_path": getattr(metadata, 'heading_path', ''),
                "chapter": metadata.chapter,
                "chapter_no": metadata.chapter_no,
                "section": metadata.section,
                "section_no": metadata.section_no,
                "subsection": getattr(metadata, 'subsection', ''),
                "subsection_no": getattr(metadata, 'subsection_no', ''),
                "page": metadata.page if hasattr(metadata, 'page') else metadata.page_start,
                "page_start": getattr(metadata, 'page_start', metadata.page if hasattr(metadata, 'page') else 0),
                "page_end": getattr(metadata, 'page_end', metadata.page if hasattr(metadata, 'page') else 0),
                "source_pages": source_pages_json,
                "parser_source": getattr(metadata, 'parser_source', 'hybrid'),
                "chunk_id": metadata.chunk_id,
                "char_count": metadata.char_count,
                "position": metadata.position,
                "ingest_time": datetime.now().isoformat(),
            }
    
    def ingest_chunks(
        self,
        chunks: list,
        source_file: str,
        batch_size: int = 30,
        skip_non_semantic: bool = True  # 默认跳过非语义块
    ) -> IngestResult:
        """批量入库分块"""
        success_count = 0
        skip_count = 0
        error_count = 0
        errors = []
        filtered_count = 0

        batch_texts = []
        batch_metadatas = []
        batch_ids = []

        for chunk in chunks:
            chunk_hash = self._compute_chunk_hash(chunk)

            if chunk_hash in self.hashes:
                skip_count += 1
                continue

            # 过滤非语义块（struct/shadow）
            if skip_non_semantic:
                chunk_type = getattr(chunk.metadata, 'chunk_type', 'semantic')
                if chunk_type in ('struct', 'shadow'):
                    filtered_count += 1
                    continue

            metadata = self._build_metadata(chunk)
            
            batch_texts.append(chunk.content)
            batch_metadatas.append(metadata)
            batch_ids.append(chunk_hash)
            
            self.hashes[chunk_hash] = source_file
            
            if len(batch_texts) >= batch_size:
                try:
                    self.vector_store.add_texts(
                        batch_texts,
                        metadatas=batch_metadatas,
                        ids=batch_ids
                    )
                    success_count += len(batch_texts)
                    print(f"    入库进度: {success_count}/{len(chunks)} (过滤非语义块: {filtered_count})")
                except Exception as e:
                    error_count += len(batch_texts)
                    errors.append(f"批量入库失败: {str(e)}")
                    for h in batch_ids:
                        self.hashes.pop(h, None)
                
                batch_texts = []
                batch_metadatas = []
                batch_ids = []
        
        if batch_texts:
            try:
                self.vector_store.add_texts(
                    batch_texts,
                    metadatas=batch_metadatas,
                    ids=batch_ids
                )
                success_count += len(batch_texts)
            except Exception as e:
                error_count += len(batch_texts)
                errors.append(f"批量入库失败: {str(e)}")
                for h in batch_ids:
                    self.hashes.pop(h, None)
        
        self._save_hashes()
        
        return IngestResult(
            source_file=source_file,
            total_chunks=len(chunks),
            success_count=success_count,
            skip_count=skip_count,
            error_count=error_count,
            filtered_count=filtered_count,
            errors=errors
        )
    
    def ingest_chunking_result(self, result, source_file: str = None) -> IngestResult:
        """入库分块结果"""
        # 兼容 V1 和 V2
        if hasattr(result, 'source_file'):
            source = result.source_file
        else:
            source = source_file or "unknown"
            # 从第一个 chunk 获取文件名
            if result.chunks and hasattr(result.chunks[0].metadata, 'source_file'):
                source = result.chunks[0].metadata.source_file
        return self.ingest_chunks(result.chunks, source)
    
    def search(
        self,
        query: str,
        k: int = 3,
        filter_course: bool = True,
        filter_chunk_type: str = None
    ) -> list[dict]:
        """检索相关文档"""
        where_filter = None
        if filter_course:
            where_filter = {"course": self.course_name}
        
        if filter_chunk_type:
            if where_filter:
                where_filter = {"$and": [
                    {"course": self.course_name},
                    {"chunk_type": filter_chunk_type}
                ]}
            else:
                where_filter = {"chunk_type": filter_chunk_type}
        
        results = self.vector_store.similarity_search_with_score(
            query,
            k=k,
            filter=where_filter
        )
        
        return [
            {
                "content": doc.page_content,
                "score": score,
                "metadata": doc.metadata
            }
            for doc, score in results
        ]
    
    def search_by_chapter(
        self,
        query: str,
        chapter_no: int,
        k: int = 3
    ) -> list[dict]:
        """按章节检索"""
        where_filter = {
            "$and": [
                {"course": self.course_name},
                {"chapter_no": chapter_no}
            ]
        }
        
        results = self.vector_store.similarity_search_with_score(
            query,
            k=k,
            filter=where_filter
        )
        
        return [
            {
                "content": doc.page_content,
                "score": score,
                "metadata": doc.metadata
            }
            for doc, score in results
        ]
    
    def get_status(self) -> KBStatus:
        """获取知识库状态"""
        try:
            count = self.vector_store._collection.count()
            sources = set(self.hashes.values())
            
            return KBStatus(
                collection_name=self.collection_name,
                course_name=self.course_name,
                document_count=count,
                last_updated=datetime.now().isoformat(),
                sources=list(sources)
            )
        except Exception as e:
            return KBStatus(
                collection_name=self.collection_name,
                course_name=self.course_name,
                document_count=0,
                last_updated=None,
                sources=[]
            )
    
    def clear(self):
        """清空知识库"""
        self.vector_store.delete_collection()
        self.vector_store = self._chroma_cls(
            collection_name=self.collection_name,
            embedding_function=self.embedding,
            persist_directory=self._config.CHROMA_PERSIST_DIR,
        )
        self.hashes = {}
        self._save_hashes()
        print(f"[KB] 知识库已清空: {self.collection_name}")


if __name__ == "__main__":
    kb = CourseKnowledgeBase()
    status = kb.get_status()
    print(f"知识库状态:")
    print(f"  Collection: {status.collection_name}")
    print(f"  课程: {status.course_name}")
    print(f"  文档数: {status.document_count}")
    print(f"  来源文件: {status.sources}")
