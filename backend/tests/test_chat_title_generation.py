from apps.api.app.routers.chat import _clean_generated_title, _finalize_title


def test_clean_generated_title_removes_prefix_and_quotes():
    assert _clean_generated_title('标题：" 下节课 时间 " ') == "下节课时间"


def test_finalize_title_keeps_week_pattern_when_llm_drops_prefix():
    title = _finalize_title("第六周的课程在几号？", "六周课几号")

    assert title.startswith("第六周")
    assert len(title) <= 10


def test_finalize_title_enforces_length_limit():
    title = _finalize_title("这是一个非常非常长的问题标题测试", "这是一个非常非常长的问题标题测试")

    assert len(title) == 10
