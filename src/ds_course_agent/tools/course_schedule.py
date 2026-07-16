"""Course schedule lookup tool."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool

import ds_course_agent.shared.config as config
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.tools._shared import _warn_large_tool_result

_SCHEDULE_CACHE: Optional[dict] = None
_SCHEDULE_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
_WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

def _load_course_schedule() -> dict:
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is not None:
        return _SCHEDULE_CACHE

    path = PROJECT_ROOT / "data" / "course_schedule.json"
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
    from ds_course_agent.rag.query_trace import trace_step, trace_error
    trace_step("tool.invoke", tool="course_schedule_tool", query=query)
    try:
        schedule = _load_course_schedule()
        result = _resolve_schedule_query_v2(query, schedule)
        trace_step("tool.result", tool="course_schedule_tool", result_preview=result[:40])
        _warn_large_tool_result("course_schedule_tool", result, status="ok")
        return result
    except Exception as exc:
        trace_error("tool.invoke", exc, tool="course_schedule_tool")
        return f"查询课程安排时出错：{exc}。请稍后重试。"

__all__ = [
    "course_schedule_tool",
    "_load_course_schedule",
    "_resolve_schedule_query_v2",
    "_resolve_schedule_query",
    "_parse_schedule_date",
    "_format_weekday_cn",
    "_format_cn_date_with_weekday",
]
