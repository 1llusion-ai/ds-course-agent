from datetime import datetime

from core.tools import _resolve_schedule_query_v2


def _build_schedule(weeks_tuesday: str = "1-8", weeks_friday: str = "1-8"):
    return {
        "course_name": "数据科学导论",
        "semester_start": "2026-03-02",
        "total_weeks": 8,
        "weekly_schedule": [
            {
                "day": "周二",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": weeks_tuesday,
            },
            {
                "day": "周五",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": weeks_friday,
            },
        ],
    }


def test_next_class_on_weekend_points_to_next_week():
    schedule = _build_schedule()

    result = _resolve_schedule_query_v2(
        "下节课是什么时候？",
        schedule,
        now=datetime(2026, 4, 12, 10, 0, 0),
    )

    assert "第7周 周二（04月14日）" in result


def test_next_class_is_sorted_by_real_datetime_not_input_order():
    schedule = {
        "course_name": "数据科学导论",
        "semester_start": "2026-03-02",
        "total_weeks": 8,
        "weekly_schedule": [
            {
                "day": "周五",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": "1-8",
            },
            {
                "day": "周二",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": "1-8",
            },
        ],
    }

    result = _resolve_schedule_query_v2(
        "下节课是什么时候？",
        schedule,
        now=datetime(2026, 4, 12, 10, 0, 0),
    )

    assert "第7周 周二（04月14日）" in result


def test_next_class_respects_weeks_range():
    schedule = _build_schedule(weeks_tuesday="1-6", weeks_friday="1-8")

    result = _resolve_schedule_query_v2(
        "下节课是什么时候？",
        schedule,
        now=datetime(2026, 4, 12, 10, 0, 0),
    )

    assert "第7周 周五（04月17日）" in result


def test_today_has_class_returns_date_and_weekday():
    schedule = _build_schedule()

    result = _resolve_schedule_query_v2(
        "今天有没有课？",
        schedule,
        now=datetime(2026, 4, 14, 9, 0, 0),
    )

    assert "今天是2026年04月14日（星期二）。" in result
    assert "今天有 1 节课" in result
    assert "第7周 周二（04月14日）第5节-第6节" in result


def test_today_no_class_returns_next_class():
    schedule = _build_schedule()

    result = _resolve_schedule_query_v2(
        "今天有课吗？",
        schedule,
        now=datetime(2026, 4, 13, 9, 0, 0),
    )

    assert "今天是2026年04月13日（星期一）。" in result
    assert "今天没有课程安排。" in result
    assert "下节课是第7周 周二（04月14日）第5节-第6节" in result


def test_semester_start_supports_slash_date_format():
    schedule = _build_schedule()
    schedule["semester_start"] = "2026/03/02"

    result = _resolve_schedule_query_v2(
        "下节课是什么时候？",
        schedule,
        now=datetime(2026, 4, 12, 10, 0, 0),
    )

    assert "第7周 周二（04月14日）" in result
