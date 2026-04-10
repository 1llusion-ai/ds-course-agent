"""
RAG Tool 模块
封装 RAG 检索与问答能力为 LangChain Tool
"""
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import tool

import utils.config as config
from core.rag import RAGService

# 动态获取章节起始页码映射
def _get_chapter_start_pages() -> dict[str, int]:
    """从目录.json动态获取章节起始页码"""
    try:
        from kb_builder.toc_parser import get_toc_parser
        toc = get_toc_parser()
        mapping = {}
        for sec in toc.sections:
            if sec.number.startswith('第') and '章' in sec.number:
                mapping[sec.number] = sec.page
        return mapping
    except Exception:
        # 回退到硬编码（如果目录加载失败）
        return {
            "第1章": 1, "第2章": 15, "第3章": 26, "第4章": 51, "第5章": 77,
            "第6章": 115, "第7章": 139, "第8章": 160, "第9章": 199, "第10章": 211,
        }

# 延迟加载的页码映射（首次调用时从目录读取）
_CHAPTER_START_PAGES: dict[str, int] = {}


_rag_service: Optional[RAGService] = None


@dataclass
class RetrievalTrace:
    used_retrieval: bool = False
    sources: list[dict] = field(default_factory=list)


_retrieval_trace: ContextVar[Optional[RetrievalTrace]] = ContextVar(
    "retrieval_trace",
    default=None,
)


def get_rag_service() -> RAGService:
    """获取 RAG 服务单例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def begin_retrieval_trace():
    return _retrieval_trace.set(RetrievalTrace())


def end_retrieval_trace(token) -> RetrievalTrace:
    trace = _retrieval_trace.get() or RetrievalTrace()
    _retrieval_trace.reset(token)
    return trace


def _merge_sources(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = list(existing)
    seen = {
        item.get("reference")
        for item in existing
        if isinstance(item, dict) and item.get("reference")
    }

    for item in incoming:
        if not isinstance(item, dict):
            continue
        reference = item.get("reference")
        if not reference or reference in seen:
            continue
        merged.append({"reference": reference})
        seen.add(reference)

    return merged


def _track_retrieval(sources: list[dict], used: bool = True) -> None:
    trace = _retrieval_trace.get()
    if trace is None:
        return

    trace.used_retrieval = trace.used_retrieval or used
    trace.sources = _merge_sources(trace.sources, sources)


def _get_absolute_page(doc) -> Optional[int]:
    """根据文档元数据计算教材的绝对页码"""
    global _CHAPTER_START_PAGES
    try:
        # 优先使用已存储的绝对页码（book_page）
        book_page = doc.metadata.get("book_page")
        if book_page is not None:
            return int(book_page)
        book_page_start = doc.metadata.get("book_page_start")
        if book_page_start is not None:
            return int(book_page_start)

        # 延迟加载页码映射
        if not _CHAPTER_START_PAGES:
            _CHAPTER_START_PAGES = _get_chapter_start_pages()

        # 获取章节号
        chapter_no = doc.metadata.get("chapter_no", "")

        # 如果chapter_no为空，尝试从chapter字段或source字段提取
        if not chapter_no:
            chapter = doc.metadata.get("chapter", "")
            # 检查chapter是否包含"第X章"
            for cn in _CHAPTER_START_PAGES.keys():
                if cn in chapter:
                    chapter_no = cn
                    break

            # 如果还没有，尝试从source文件名提取
            if not chapter_no:
                source = doc.metadata.get("source", "")
                import re
                match = re.search(r'_第(\d+)章', source)
                if match:
                    chapter_no = f"第{match.group(1)}章"

        # 获取章节起始页
        chapter_start = _CHAPTER_START_PAGES.get(chapter_no)
        if chapter_start is None:
            return None

        # 获取文档中的相对页码
        rel_page = doc.metadata.get("page")
        if rel_page is None:
            rel_page = doc.metadata.get("page_start")

        if rel_page is not None:
            # 计算绝对页码：章节起始页 + 相对页码 - 1
            return chapter_start + int(rel_page) - 1

        return None
    except Exception:
        return None


def build_sources_from_documents(documents) -> list[dict]:
    sources: list[dict] = []

    for doc in documents or []:
        metadata = getattr(doc, "metadata", {}) or {}
        source = metadata.get("source", "未知来源")
        chapter = metadata.get("chapter", "")
        chapter_no = metadata.get("chapter_no", "")

        if not chapter_no:
            match = re.search(r"第(\d+)章", source)
            if match:
                chapter_no = f"第{match.group(1)}章"

        abs_page = _get_absolute_page(doc)

        if chapter:
            if abs_page and chapter_no:
                reference = f"《{chapter_no} {chapter}》第{abs_page}页"
            elif abs_page:
                reference = f"《{chapter}》第{abs_page}页"
            elif chapter_no:
                reference = f"《{chapter_no} {chapter}》"
            else:
                reference = f"《{chapter}》"
        else:
            reference = os.path.basename(source)

        if reference not in [item["reference"] for item in sources]:
            sources.append({"reference": reference})

    return sources


@tool
def course_rag_tool(question: str) -> str:
    """
    课程资料检索与问答工具。
    
    用于在《数据科学导论》课程知识库中检索相关资料并回答问题。
    支持概念答疑、课程资料问答、学习建议等场景。
    
    当用户询问与课程内容、概念解释、学习方法相关的问题时，应使用此工具。
    
    Args:
        question: 用户的问题，如"什么是数据挖掘？"、"如何学习机器学习？"
        
    Returns:
        str: 基于课程资料的回答，包含来源引用
    """
    try:
        service = get_rag_service()
        
        result = service.retrieve(question)
        sources = build_sources_from_documents(result.documents)
        _track_retrieval(sources, used=True)
        
        if not result.has_results:
            return f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与您问题相关的内容。建议您：\n1. 尝试用不同的关键词重新提问\n2. 检查问题是否与课程主题相关\n3. 联系助教获取更多帮助"
        
        answer_result = service.answer_with_context(question, result.formatted_context)

        response = answer_result.answer

        return response
        
    except Exception as e:
        return f"检索过程中发生错误：{str(e)}。请稍后重试或联系技术支持。"


@tool
def check_knowledge_base_status() -> str:
    """
    检查知识库状态工具。
    
    用于检查课程知识库是否正常工作，以及当前知识库的基本信息。
    
    Returns:
        str: 知识库状态信息
    """
    try:
        service = get_rag_service()
        
        test_result = service.retrieve("测试", top_k=1)
        
        return f"✅ 知识库状态正常\n📚 课程名称：{config.COURSE_NAME}\n📝 课程范围：{config.COURSE_DESCRIPTION}\n🔍 检索功能：正常"
        
    except Exception as e:
        return f"❌ 知识库状态异常：{str(e)}"


def get_rag_tools():
    """获取所有 RAG 相关工具列表"""
    return [course_rag_tool, check_knowledge_base_status]


if __name__ == "__main__":
    print("测试 course_rag_tool:")
    result = course_rag_tool.invoke("什么是数据科学？")
    print(result)
