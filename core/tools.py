"""
RAG Tool 模块
封装 RAG 检索与问答能力为 LangChain Tool
"""
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


# ========== 课程日历工具 ==========

_SCHEDULE_CACHE: Optional[dict] = None


def _load_course_schedule() -> dict:
    """加载课程安排 JSON"""
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is not None:
        return _SCHEDULE_CACHE

    path = Path(__file__).parent.parent / "data" / "course_schedule.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            _SCHEDULE_CACHE = json.load(f)
    else:
        _SCHEDULE_CACHE = {}
    return _SCHEDULE_CACHE or {}


def _get_week_start(semester_start: str, week: int) -> datetime:
    """计算第 week 周的周一日期"""
    start = datetime.strptime(semester_start, "%Y-%m-%d")
    return start + timedelta(days=7 * (week - 1))


def _week_to_dates(semester_start: str, week: int) -> dict:
    """将第几周映射到具体日期范围"""
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


def _resolve_schedule_query(query: str, schedule: dict) -> str:
    """解析课程安排查询"""
    if not schedule:
        return "抱歉，课程安排信息暂未配置。"

    semester_start = schedule.get("semester_start", "")
    total_weeks = schedule.get("total_weeks", 0)
    weekly_schedule = schedule.get("weekly_schedule", [])

    if not semester_start or not weekly_schedule:
        return "课程安排数据不完整，请联系助教补充。"

    today = datetime.now()
    start_date = datetime.strptime(semester_start, "%Y-%m-%d")
    current_week = max(1, (today - start_date).days // 7 + 1)

    q = query.lower().strip()

    # 判断是否问总周数
    if any(k in q for k in ["上几周", "多少周", "总周数", "到第几周"]):
        return f"《{config.COURSE_NAME}》本学期共 {total_weeks} 周，从 {semester_start} 开始。"

    # 判断是否问特定周
    for w in range(1, total_weeks + 1):
        if f"第{w}周" in q or f"第 {w} 周" in q:
            dates = _week_to_dates(semester_start, w)
            lines = [f"第{w}周（{dates['周一'].strftime('%m月%d日')} ~ {dates['周日'].strftime('%m月%d日')}）的课程安排："]
            for item in weekly_schedule:
                day = item.get("day", "")
                date_str = dates.get(day, dates.get("周" + day[-1] if day.endswith(("一", "二", "三", "四", "五", "六", "日")) else day))
                if isinstance(date_str, datetime):
                    date_str = date_str.strftime("%m月%d日")
                lines.append(f"- {day}（{date_str}）{item.get('period', '')}，教室：{item.get('room', '')}")
            return "\n".join(lines)

    # 下节课 / 最近
    if any(k in q for k in ["下节课", "什么时候上课", "上课", "课程时间", "教室"]):
        upcoming = []
        for week in range(current_week, total_weeks + 1):
            dates = _week_to_dates(semester_start, week)
            for item in weekly_schedule:
                day = item.get("day", "")
                class_date = dates.get(day)
                if class_date is None and day.endswith(("一", "二", "三", "四", "五", "六", "日")):
                    class_date = dates.get("周" + day[-1])
                if class_date is None:
                    continue
                class_datetime = class_date.replace(hour=14, minute=30)  # 第5节约14:30
                if class_datetime >= today:
                    upcoming.append({
                        "week": week,
                        "day": day,
                        "date": class_date.strftime("%m月%d日"),
                        "period": item.get("period", ""),
                        "room": item.get("room", ""),
                        "datetime": class_datetime,
                    })
            if upcoming:
                break

        if not upcoming:
            return f"本学期课程已结束（共{total_weeks}周）。"

        next_class = upcoming[0]
        # 本周全部课程
        this_week_classes = [u for u in upcoming if u["week"] == current_week]
        if any(k in q for k in ["这周", "本周", "今天", "明天", "后天"]):
            if this_week_classes:
                lines = [f"本周（第{current_week}周）有 {len(this_week_classes)} 次课："]
                for c in this_week_classes:
                    lines.append(f"- {c['day']}（{c['date']}）{c['period']}，教室：{c['room']}")
                return "\n".join(lines)
            else:
                return f"本周（第{current_week}周）没有课程安排。"

        return (
            f"下节课是第{next_class['week']}周 {next_class['day']}（{next_class['date']}）"
            f"{next_class['period']}，教室：{next_class['room']}。"
        )

    # 默认返回全部安排
    lines = [f"《{config.COURSE_NAME}》课程安排（共{total_weeks}周）："]
    for item in weekly_schedule:
        lines.append(f"- {item.get('day', '')} {item.get('period', '')}，教室：{item.get('room', '')}（{item.get('weeks', '')}）")
    return "\n".join(lines)


@tool
def course_schedule_tool(query: str) -> str:
    """
    课程日程查询工具。

    用于回答学生关于上课时间、教室、周次安排等问题。
    支持查询：下节课时间、本周课程、第N周课程、课程总周数、教室位置等。

    Args:
        query: 学生的查询内容，如"下节课是什么时候"、"这周在哪上课"、"第5周课程安排"

    Returns:
        str: 课程安排信息
    """
    try:
        schedule = _load_course_schedule()
        return _resolve_schedule_query(query, schedule)
    except Exception as e:
        return f"查询课程安排时出错：{str(e)}。请稍后重试或联系助教。"


def _schedule_parse_weeks_spec_v2(weeks: str) -> set[int]:
    parsed: set[int] = set()
    if not weeks:
        return parsed

    for part in re.split(r"[，,\s]+", weeks.strip()):
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
    active_weeks = _schedule_parse_weeks_spec_v2(item.get("weeks", ""))
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
    if day.endswith(("一", "二", "三", "四", "五", "六", "日")):
        return dates.get(f"周{day[-1]}")
    return None


def _schedule_build_week_classes_v2(semester_start: str, weekly_schedule: list[dict], week: int) -> list[dict]:
    dates = _week_to_dates(semester_start, week)
    classes = []

    for item in weekly_schedule:
        if not _schedule_is_active_in_week_v2(item, week):
            continue

        day = item.get("day", "")
        class_date = _schedule_resolve_day_v2(dates, day)
        if class_date is None:
            continue

        start_hour, start_minute = _schedule_period_start_v2(item.get("period", ""))
        classes.append({
            "week": week,
            "day": day,
            "date": class_date.strftime("%m月%d日"),
            "period": item.get("period", ""),
            "room": item.get("room", ""),
            "datetime": class_date.replace(hour=start_hour, minute=start_minute),
        })

    classes.sort(key=lambda item: item["datetime"])
    return classes


def _resolve_schedule_query_v2(query: str, schedule: dict, now: Optional[datetime] = None) -> str:
    if not schedule:
        return "抱歉，课程安排信息暂未配置。"

    semester_start = schedule.get("semester_start", "")
    total_weeks = schedule.get("total_weeks", 0)
    weekly_schedule = schedule.get("weekly_schedule", [])

    if not semester_start or not weekly_schedule:
        return "课程安排数据不完整，请联系助教补充。"

    today = now or datetime.now()
    start_date = datetime.strptime(semester_start, "%Y-%m-%d")
    current_week = max(1, (today.date() - start_date.date()).days // 7 + 1)

    q = query.lower().strip()

    if any(keyword in q for keyword in ["上几周", "多少周", "总周数", "到第几周"]):
        return f"《{config.COURSE_NAME}》本学期共 {total_weeks} 周，从 {semester_start} 开始。"

    for week in range(1, total_weeks + 1):
        if f"第{week}周" not in q and f"第 {week} 周" not in q:
            continue

        dates = _week_to_dates(semester_start, week)
        lines = [
            f"第{week}周（{dates['周一'].strftime('%m月%d日')} ~ {dates['周日'].strftime('%m月%d日')}）的课程安排："
        ]
        for class_info in _schedule_build_week_classes_v2(semester_start, weekly_schedule, week):
            lines.append(
                f"- {class_info['day']}（{class_info['date']}）{class_info['period']}，教室：{class_info['room']}"
            )
        return "\n".join(lines)

    if any(keyword in q for keyword in ["下节课", "什么时候上课", "上课", "课程时间", "教室"]):
        upcoming = []
        for week in range(current_week, total_weeks + 1):
            future_classes = [
                item
                for item in _schedule_build_week_classes_v2(semester_start, weekly_schedule, week)
                if item["datetime"] >= today
            ]
            if future_classes:
                upcoming = future_classes
                break

        if not upcoming:
            return f"本学期课程已结束（共{total_weeks}周）。"

        next_class = upcoming[0]
        this_week_classes = _schedule_build_week_classes_v2(semester_start, weekly_schedule, current_week)

        if any(keyword in q for keyword in ["这周", "本周", "今天", "明天", "后天"]):
            if this_week_classes:
                lines = [f"本周（第{current_week}周）有 {len(this_week_classes)} 次课："]
                for class_info in this_week_classes:
                    lines.append(
                        f"- {class_info['day']}（{class_info['date']}）{class_info['period']}，教室：{class_info['room']}"
                    )
                return "\n".join(lines)
            return f"本周（第{current_week}周）没有课程安排。"

        return (
            f"下节课是第{next_class['week']}周 {next_class['day']}（{next_class['date']}）"
            f"{next_class['period']}，教室：{next_class['room']}。"
        )

    lines = [f"《{config.COURSE_NAME}》课程安排（共{total_weeks}周）："]
    for item in weekly_schedule:
        lines.append(
            f"- {item.get('day', '')} {item.get('period', '')}，教室：{item.get('room', '')}（{item.get('weeks', '')}）"
        )
    return "\n".join(lines)


@tool
def course_schedule_tool(query: str) -> str:
    """课程日程查询工具。"""
    try:
        schedule = _load_course_schedule()
        return _resolve_schedule_query_v2(query, schedule)
    except Exception as e:
        return f"查询课程安排时出错：{str(e)}。请稍后重试或联系助教。"


def get_rag_tools():
    """获取所有 RAG 相关工具列表"""
    return [course_rag_tool, check_knowledge_base_status, course_schedule_tool]


if __name__ == "__main__":
    print("测试 course_rag_tool:")
    result = course_rag_tool.invoke("什么是数据科学？")
    print(result)
