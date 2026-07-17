from ds_course_agent.api.routers.chat import _clean_generated_title, _finalize_title
from ds_course_agent.api.title_generation import SESSION_TITLE_MAX_CHARS, build_fallback_session_title


def test_clean_generated_title_removes_prefix_and_quotes():
    assert _clean_generated_title('标题：" 下节课 时间 " ') == "下节课时间"


def test_finalize_title_keeps_week_pattern_when_llm_drops_prefix():
    title = _finalize_title("第六周的课程在几号？", "六周课几号")

    assert title.startswith("第六周")
    assert len(title) <= SESSION_TITLE_MAX_CHARS


def test_finalize_title_enforces_length_limit():
    title = _finalize_title(
        "这是一个非常非常长的问题标题测试，想了解一下相关背景",
        "一个明显超过限制的学习会话标题应该被截断",
    )

    assert len(title) == SESSION_TITLE_MAX_CHARS


def test_finalize_title_repairs_raw_question_prefix():
    title = _finalize_title("逻辑回归为什么能做分类？", "逻辑回归为什么能做分")

    assert title == "逻辑回归分类原理"


def test_fallback_title_is_topic_like_not_raw_slice():
    assert build_fallback_session_title("请用 Python 演示一次交叉验证") == "Python 交叉验证演示"
    assert build_fallback_session_title("帮我区分过拟合和欠拟合") == "过拟合与欠拟合区分"
    assert build_fallback_session_title("给我推荐一个学习机器学习的路径") == "机器学习路径推荐"
    assert build_fallback_session_title("机器学习有哪些方法？") == "机器学习方法"


def test_fallback_title_collapses_repeated_general_fact_query():
    repeated = "菲律宾的现任总统是谁" * 3

    assert build_fallback_session_title(repeated) == "菲律宾现任总统"
    assert build_fallback_session_title("菲律宾的现任总统是谁") == "菲律宾现任总统"
    assert build_fallback_session_title("美国总统是谁") == "美国现任总统"
    assert build_fallback_session_title("詹姆斯多大了？") == "詹姆斯年龄"
