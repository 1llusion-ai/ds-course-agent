"""RAG and schedule tools used by the teaching agent."""

from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

import utils.config as config
from core.rag import RAGService


def _get_chapter_start_pages() -> dict[str, int]:
    """Load chapter start pages from the TOC parser when available."""
    try:
        from kb_builder.toc_parser import get_toc_parser

        toc = get_toc_parser()
        mapping: dict[str, int] = {}
        for section in toc.sections:
            number = getattr(section, "number", "")
            page = getattr(section, "page", None)
            if not isinstance(number, str) or page is None:
                continue
            if number.startswith("第") and "章" in number:
                mapping[number] = int(page)
        if mapping:
            return mapping
    except Exception:
        pass

    return {
        "第1章": 1,
        "第2章": 15,
        "第3章": 26,
        "第4章": 51,
        "第5章": 77,
        "第6章": 115,
        "第7章": 139,
        "第8章": 160,
        "第9章": 199,
        "第10章": 211,
    }


_CHAPTER_START_PAGES: dict[str, int] = {}
_SCHEDULE_CACHE: Optional[dict] = None
_rag_service: Optional[RAGService] = None
_SCHEDULE_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
_WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@dataclass
class RetrievalTrace:
    used_retrieval: bool = False
    sources: list[dict] = field(default_factory=list)


_retrieval_trace: ContextVar[Optional[RetrievalTrace]] = ContextVar(
    "retrieval_trace",
    default=None,
)


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def begin_retrieval_trace():
    existing = _retrieval_trace.get()
    if existing is not None:
        return None
    return _retrieval_trace.set(RetrievalTrace())


def end_retrieval_trace(token) -> RetrievalTrace:
    if token is None:
        return _retrieval_trace.get() or RetrievalTrace()
    trace = _retrieval_trace.get() or RetrievalTrace()
    _retrieval_trace.reset(token)
    return trace


def get_retrieval_trace() -> RetrievalTrace:
    return _retrieval_trace.get() or RetrievalTrace()


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


def _extract_chapter_no(metadata: dict) -> str:
    chapter_no = str(metadata.get("chapter_no") or "").strip()
    if chapter_no:
        return chapter_no

    chapter = str(metadata.get("chapter") or "")
    match = re.search(r"第\s*(\d+)\s*章", chapter)
    if match:
        return f"第{match.group(1)}章"

    source = str(metadata.get("source") or "")
    match = re.search(r"第\s*(\d+)\s*章", source)
    if match:
        return f"第{match.group(1)}章"

    return ""


def _get_absolute_page(doc) -> Optional[int]:
    """Convert chunk-local page information into textbook absolute pages."""
    global _CHAPTER_START_PAGES

    metadata = getattr(doc, "metadata", {}) or {}

    direct_page = metadata.get("book_page")
    if direct_page is not None:
        return int(direct_page)

    direct_page = metadata.get("book_page_start")
    if direct_page is not None:
        return int(direct_page)

    if not _CHAPTER_START_PAGES:
        _CHAPTER_START_PAGES = _get_chapter_start_pages()

    chapter_no = _extract_chapter_no(metadata)
    chapter_start = _CHAPTER_START_PAGES.get(chapter_no)
    if chapter_start is None:
        return None

    relative_page = metadata.get("page")
    if relative_page is None:
        relative_page = metadata.get("page_start")
    if relative_page is None:
        return None

    return chapter_start + int(relative_page) - 1


def build_sources_from_documents(documents) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()

    for doc in documents or []:
        metadata = getattr(doc, "metadata", {}) or {}
        chapter = str(metadata.get("chapter") or "").strip()
        chapter_no = _extract_chapter_no(metadata)
        abs_page = _get_absolute_page(doc)

        if chapter and chapter_no and abs_page:
            reference = f"《{chapter_no} {chapter}》第{abs_page}页"
        elif chapter and abs_page:
            reference = f"《{chapter}》第{abs_page}页"
        elif chapter and chapter_no:
            reference = f"《{chapter_no} {chapter}》"
        elif chapter:
            reference = f"《{chapter}》"
        else:
            reference = os.path.basename(str(metadata.get("source") or "未知来源"))

        if reference in seen:
            continue
        seen.add(reference)
        sources.append({"reference": reference})

    return sources


@tool
def course_rag_tool(question: str) -> str:
    """课程资料检索与问答工具。用于基于教材内容回答课程相关问题。"""
    from core.query_trace import trace_step, trace_error
    trace_step("tool.invoke", tool="course_rag_tool", question=question)
    try:
        service = get_rag_service()
        result = service.retrieve(question)
        sources = build_sources_from_documents(result.documents)
        _track_retrieval(sources, used=True)

        if not result.has_results:
            trace_step("tool.result", tool="course_rag_tool", status="no_results")
            return (
                f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与你问题直接相关的内容。\n"
                "建议你：\n"
                "1. 换一个更具体的关键词重新提问\n"
                "2. 说明你想问的概念、章节或例子\n"
                "3. 如果是课程外问题，我也可以先帮你判断是否属于本课程范围"
            )

        answer_result = service.answer_with_context(question, result.formatted_context)
        trace_step("tool.result", tool="course_rag_tool", status="ok")
        return answer_result.answer
    except Exception as exc:
        trace_error("tool.invoke", exc, tool="course_rag_tool")
        return f"检索过程中发生错误：{exc}。请稍后重试。"


@tool
def check_knowledge_base_status() -> str:
    """检查当前课程知识库状态。"""
    try:
        service = get_rag_service()
        service.retrieve("测试", top_k=1)
        return (
            "知识库状态正常\n"
            f"课程名称：{config.COURSE_NAME}\n"
            f"课程范围：{config.COURSE_DESCRIPTION}\n"
            "检索功能：可用"
        )
    except Exception as exc:
        return f"知识库状态异常：{exc}"


def _load_course_schedule() -> dict:
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is not None:
        return _SCHEDULE_CACHE

    path = Path(__file__).parent.parent / "data" / "course_schedule.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            _SCHEDULE_CACHE = json.load(handle)
    else:
        _SCHEDULE_CACHE = {}
    return _SCHEDULE_CACHE or {}


def _parse_schedule_date(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    for date_format in _SCHEDULE_DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _format_weekday_cn(value: datetime) -> str:
    return _WEEKDAY_CN[value.weekday()]


def _format_cn_date_with_weekday(value: datetime) -> str:
    return f"{value.strftime('%Y年%m月%d日')}（{_format_weekday_cn(value)}）"


def _get_week_start(semester_start: str, week: int) -> datetime:
    start = _parse_schedule_date(semester_start)
    if start is None:
        raise ValueError(
            "semester_start 日期格式无效，支持 YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYY年MM月DD日"
        )
    return start + timedelta(days=7 * (week - 1))


def _week_to_dates(semester_start: str, week: int) -> dict[str, datetime]:
    monday = _get_week_start(semester_start, week)
    return {
        "周一": monday,
        "周二": monday + timedelta(days=1),
        "周三": monday + timedelta(days=2),
        "周四": monday + timedelta(days=3),
        "周五": monday + timedelta(days=4),
        "周六": monday + timedelta(days=5),
        "周日": monday + timedelta(days=6),
    }


def _schedule_parse_weeks_spec_v2(weeks: str) -> set[int]:
    parsed: set[int] = set()
    if not weeks:
        return parsed

    normalized = (
        weeks.replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace("至", "-")
        .replace("~", "-")
    )

    for part in re.split(r"[\s,]+", normalized.strip()):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if start_text.isdigit() and end_text.isdigit():
                start = int(start_text)
                end = int(end_text)
                if start <= end:
                    parsed.update(range(start, end + 1))
            continue
        if part.isdigit():
            parsed.add(int(part))

    return parsed


def _schedule_is_active_in_week_v2(item: dict, week: int) -> bool:
    active_weeks = _schedule_parse_weeks_spec_v2(str(item.get("weeks", "")))
    if not active_weeks:
        return True
    return week in active_weeks


def _schedule_period_start_v2(period: str) -> tuple[int, int]:
    match = re.search(r"第\s*(\d+)\s*节", period or "")
    if not match:
        return (8, 0)

    start_time_map = {
        1: (8, 0),
        2: (8, 55),
        3: (10, 10),
        4: (11, 5),
        5: (14, 30),
        6: (15, 25),
        7: (16, 20),
        8: (17, 15),
        9: (19, 0),
        10: (19, 55),
        11: (20, 50),
    }
    return start_time_map.get(int(match.group(1)), (8, 0))


def _schedule_resolve_day_v2(dates: dict[str, datetime], day: str) -> Optional[datetime]:
    if day in dates:
        return dates[day]

    aliases = {
        "星期一": "周一",
        "星期二": "周二",
        "星期三": "周三",
        "星期四": "周四",
        "星期五": "周五",
        "星期六": "周六",
        "星期日": "周日",
        "星期天": "周日",
    }
    alias = aliases.get(day)
    if alias:
        return dates.get(alias)
    return None


def _schedule_build_week_classes_v2(semester_start: str, weekly_schedule: list[dict], week: int) -> list[dict]:
    dates = _week_to_dates(semester_start, week)
    classes: list[dict] = []

    for item in weekly_schedule:
        if not _schedule_is_active_in_week_v2(item, week):
            continue

        day = str(item.get("day", ""))
        class_date = _schedule_resolve_day_v2(dates, day)
        if class_date is None:
            continue

        start_hour, start_minute = _schedule_period_start_v2(str(item.get("period", "")))
        classes.append(
            {
                "week": week,
                "day": day,
                "date": class_date.strftime("%m月%d日"),
                "period": str(item.get("period", "")),
                "room": str(item.get("room", "")),
                "weeks": str(item.get("weeks", "")),
                "datetime": class_date.replace(hour=start_hour, minute=start_minute),
            }
        )

    classes.sort(key=lambda item: item["datetime"])
    return classes


def _schedule_build_all_classes_v2(
    semester_start: str,
    weekly_schedule: list[dict],
    total_weeks: int,
) -> list[dict]:
    classes: list[dict] = []
    for week in range(1, total_weeks + 1):
        classes.extend(_schedule_build_week_classes_v2(semester_start, weekly_schedule, week))
    classes.sort(key=lambda item: item["datetime"])
    return classes


def _schedule_query_day_offset_v2(normalized_query: str) -> Optional[int]:
    if "今天" in normalized_query:
        return 0
    if "明天" in normalized_query:
        return 1
    if "后天" in normalized_query:
        return 2
    return None


def _schedule_is_day_query_v2(normalized_query: str) -> bool:
    offset = _schedule_query_day_offset_v2(normalized_query)
    if offset is None:
        return False

    day_intent_cues = [
        "有课",
        "有没有课",
        "是否有课",
        "上课",
        "课程安排",
        "几节课",
        "课吗",
        "课嘛",
    ]
    return any(cue in normalized_query for cue in day_intent_cues)


def _format_next_class_v2(class_info: dict) -> str:
    return (
        f"下节课是第{class_info['week']}周 {class_info['day']}（{class_info['date']}）"
        f"{class_info['period']}，教室：{class_info['room']}。"
    )


def _resolve_schedule_query_v2(query: str, schedule: dict, now: Optional[datetime] = None) -> str:
    if not schedule:
        return "抱歉，课程安排信息暂未配置。"

    semester_start = str(schedule.get("semester_start", "")).strip()
    total_weeks = int(schedule.get("total_weeks", 0) or 0)
    weekly_schedule = schedule.get("weekly_schedule", []) or []

    if not semester_start or not weekly_schedule:
        return "课程安排数据不完整，请联系助教补充。"

    today = now or datetime.now()
    start_date = _parse_schedule_date(semester_start)
    if start_date is None:
        return (
            "课程安排中的 semester_start 日期格式不正确。"
            "请使用 YYYY-MM-DD（也支持 YYYY/MM/DD、YYYY.MM.DD、YYYY年MM月DD日）。"
        )

    semester_start_display = start_date.strftime("%Y-%m-%d")
    current_week = max(1, (today.date() - start_date.date()).days // 7 + 1)
    current_week = min(current_week, total_weeks) if total_weeks > 0 else current_week
    all_classes = _schedule_build_all_classes_v2(semester_start, weekly_schedule, total_weeks)
    upcoming = [item for item in all_classes if item["datetime"] >= today]

    q = re.sub(r"\s+", "", query.lower())

    if any(keyword in q for keyword in ["上几周", "多少周", "总周数", "到第几周"]):
        return f"《{config.COURSE_NAME}》本学期共 {total_weeks} 周，从 {semester_start_display} 开始。"

    for week in range(1, total_weeks + 1):
        if f"第{week}周" not in q:
            continue

        dates = _week_to_dates(semester_start, week)
        lines = [
            f"第{week}周（{dates['周一'].strftime('%m月%d日')} ~ {dates['周日'].strftime('%m月%d日')}）的课程安排："
        ]
        classes = _schedule_build_week_classes_v2(semester_start, weekly_schedule, week)
        if not classes:
            lines.append("- 本周没有排课")
        else:
            for class_info in classes:
                lines.append(
                    f"- {class_info['day']}（{class_info['date']}）{class_info['period']}，教室：{class_info['room']}"
                )
        return "\n".join(lines)

    schedule_keywords = [
        "下节课",
        "下次课",
        "下次上课",
        "什么时候上课",
        "上课时间",
        "课程时间",
        "教室",
        "课程安排",
        "课表",
        "今天有课吗",
        "今天有没有课",
        "明天有课吗",
        "明天有没有课",
        "后天有课吗",
        "后天有没有课",
    ]
    if any(keyword in q for keyword in schedule_keywords):
        if _schedule_is_day_query_v2(q):
            day_offset = _schedule_query_day_offset_v2(q) or 0
            day_label = ("今天", "明天", "后天")[day_offset] if day_offset <= 2 else "当天"
            target_day = (today + timedelta(days=day_offset)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            target_classes = [
                item for item in all_classes if item["datetime"].date() == target_day.date()
            ]

            lines = [f"{day_label}是{_format_cn_date_with_weekday(target_day)}。"]
            if target_classes:
                lines.append(f"{day_label}有 {len(target_classes)} 节课：")
                for class_info in target_classes:
                    lines.append(
                        f"- 第{class_info['week']}周 {class_info['day']}（{class_info['date']}）"
                        f"{class_info['period']}，教室：{class_info['room']}"
                    )
                return "\n".join(lines)

            lines.append(f"{day_label}没有课程安排。")
            next_after_target = next(
                (item for item in all_classes if item["datetime"] >= target_day),
                None,
            )
            if next_after_target:
                lines.append(_format_next_class_v2(next_after_target))
            elif upcoming:
                lines.append(_format_next_class_v2(upcoming[0]))
            return "\n".join(lines)

        if not upcoming:
            return f"本学期课程已结束（共 {total_weeks} 周）。"

        if any(keyword in q for keyword in ["这周", "本周"]):
            this_week_classes = _schedule_build_week_classes_v2(semester_start, weekly_schedule, current_week)
            if not this_week_classes:
                return f"本周（第{current_week}周）没有课程安排。"

            lines = [f"本周（第{current_week}周）共有 {len(this_week_classes)} 次课："]
            for class_info in this_week_classes:
                lines.append(
                    f"- {class_info['day']}（{class_info['date']}）{class_info['period']}，教室：{class_info['room']}"
                )
            return "\n".join(lines)

        return _format_next_class_v2(upcoming[0])

    lines = [f"《{config.COURSE_NAME}》课程安排（共 {total_weeks} 周）："]
    for item in weekly_schedule:
        lines.append(
            f"- {item.get('day', '')} {item.get('period', '')}，教室：{item.get('room', '')}（{item.get('weeks', '')}）"
        )
    return "\n".join(lines)


def _resolve_schedule_query(query: str, schedule: dict) -> str:
    """Legacy alias kept for compatibility."""
    return _resolve_schedule_query_v2(query, schedule)


@tool
def course_schedule_tool(query: str) -> str:
    """课程时间查询工具。用于回答上课时间、教室、周次安排等问题。"""
    from core.query_trace import trace_step, trace_error
    trace_step("tool.invoke", tool="course_schedule_tool", query=query)
    try:
        schedule = _load_course_schedule()
        result = _resolve_schedule_query_v2(query, schedule)
        trace_step("tool.result", tool="course_schedule_tool", result_preview=result[:40])
        return result
    except Exception as exc:
        trace_error("tool.invoke", exc, tool="course_schedule_tool")
        return f"查询课程安排时出错：{exc}。请稍后重试。"


@tool
def current_datetime_tool(query: str = "") -> str:
    """当前日期时间查询工具。用于回答今天几号、星期几、现在几点。"""
    from core.query_trace import trace_step
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
    return result


def get_rag_tools():
    return [course_rag_tool, check_knowledge_base_status, course_schedule_tool, current_datetime_tool]


if __name__ == "__main__":
    print("测试 course_rag_tool:")
    print(course_rag_tool.invoke("什么是数据科学？"))
