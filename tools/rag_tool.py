"""
RAG Tool 模块
封装 RAG 检索与问答能力为 LangChain Tool
"""
import os
from typing import Optional

from langchain_core.tools import tool

import config_data as config
from rag import RAGService


_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """获取 RAG 服务单例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


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
        
        if not result.has_results:
            return f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与您问题相关的内容。建议您：\n1. 尝试用不同的关键词重新提问\n2. 检查问题是否与课程主题相关\n3. 联系助教获取更多帮助"
        
        sources_info = []
        for doc in result.documents:
            source = doc.metadata.get("source", "未知来源")
            chapter = doc.metadata.get("chapter", "")
            # 构建更详细的来源信息
            if chapter:
                source_display = f"《{chapter}》（{os.path.basename(source)}）"
            else:
                source_display = os.path.basename(source)
            if source_display not in sources_info:
                sources_info.append(source_display)
        
        answer_result = service.answer_with_context(question, result.formatted_context)
        
        response = answer_result.answer
        
        if sources_info:
            response += f"\n\n📚 参考来源：{', '.join(sources_info)}"
        
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
