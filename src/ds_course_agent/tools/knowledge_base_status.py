"""Knowledge-base status tool."""

from __future__ import annotations

from langchain_core.tools import tool

import ds_course_agent.shared.config as config
from ds_course_agent.tools._shared import _warn_large_tool_result, get_rag_service


@tool
def check_knowledge_base_status() -> str:
    """检查当前课程知识库状态。"""
    try:
        service = get_rag_service()
        service.retrieve("测试", top_k=1)
        result = (
            f"知识库状态正常\n课程名称：{config.COURSE_NAME}\n课程范围：{config.COURSE_DESCRIPTION}\n检索功能：可用"
        )
        _warn_large_tool_result("check_knowledge_base_status", result, status="ok")
        return result
    except Exception as exc:
        result = f"知识库状态异常：{exc}"
        _warn_large_tool_result("check_knowledge_base_status", result, status="error")
        return result


__all__ = ["check_knowledge_base_status"]
