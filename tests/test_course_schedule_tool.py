from datetime import datetime

from core.tools import _resolve_schedule_query_v2


def test_next_class_on_weekend_points_to_next_week():
    schedule = {
        "course_name": "数据科学导论",
        "semester_start": "2026-03-02",
        "total_weeks": 8,
        "weekly_schedule": [
            {
                "day": "周二",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": "1-8",
            },
            {
                "day": "周五",
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
    schedule = {
        "course_name": "数据科学导论",
        "semester_start": "2026-03-02",
        "total_weeks": 8,
        "weekly_schedule": [
            {
                "day": "周二",
                "period": "第5节-第6节",
                "room": "庄汉水楼（南强二）305",
                "weeks": "1-6",
            },
            {
                "day": "周五",
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

    assert "第7周 周五（04月17日）" in result
