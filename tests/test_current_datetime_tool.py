import re

from core.tools import current_datetime_tool


def test_current_datetime_tool_contains_date_time_and_weekday():
    result = current_datetime_tool.invoke("今天星期几？")

    assert "当前时间：" in result
    assert "今天是" in result
    assert "星期" in result
    assert re.search(r"\d{4}-\d{2}-\d{2}", result)
    assert re.search(r"\d{2}:\d{2}:\d{2}", result)
