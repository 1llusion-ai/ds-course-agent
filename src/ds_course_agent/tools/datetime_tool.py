"""Current date/time tool."""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from ds_course_agent.tools._shared import _warn_large_tool_result

_WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _format_weekday_cn(value: datetime) -> str:
    return _WEEKDAY_CN[value.weekday()]


@tool
def current_datetime_tool(query: str = "") -> str:
    """当前日期时间查询工具。用于回答今天几号、星期几、现在几点。"""
    from ds_course_agent.rag.query_trace import trace_step

    trace_step("tool.invoke", tool="current_datetime_tool")
    now = datetime.now().astimezone()
    offset = now.strftime("%z")
    if offset:
        offset_display = f"UTC{offset[:3]}:{offset[3:]}"
    else:
        offset_display = "本地时区"

    result = (
        f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（{_format_weekday_cn(now)}，{offset_display}）\n"
        f"今天是 {now.strftime('%Y年%m月%d日')}。"
    )
    trace_step("tool.result", tool="current_datetime_tool")
    _warn_large_tool_result("current_datetime_tool", result, status="ok")
    return result


__all__ = ["current_datetime_tool", "_format_weekday_cn"]
