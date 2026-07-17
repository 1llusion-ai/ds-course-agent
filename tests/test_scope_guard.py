from ds_course_agent.rag.scope_guard import assess_query_scope


def test_scope_guard_blocks_general_sports_fact():
    decision = assess_query_scope("詹姆斯多大了？", web_search_requested=True)

    assert decision.allowed is False
    assert decision.category == "sports_or_celebrity_fact"
    assert "本次不进行通用联网搜索" in decision.response
    assert "体育数据科学项目" in decision.response


def test_scope_guard_blocks_general_political_fact():
    decision = assess_query_scope("美国总统是谁？", web_search_requested=True)

    assert decision.allowed is False
    assert decision.category == "politics_general_fact"
    assert "历任总统年龄" in decision.response


def test_scope_guard_allows_data_science_framing_of_off_topic_subjects():
    assert assess_query_scope("用 Python 分析 NBA 球员年龄分布").allowed is True
    assert assess_query_scope("美国总统年龄有什么统计规律？").allowed is True
    assert assess_query_scope("股票收益率怎么建模？").allowed is True


def test_scope_guard_allows_course_and_ai_questions():
    assert assess_query_scope("DAPO 是什么？", web_search_requested=True).allowed is True
    assert assess_query_scope("GitHub 上有哪些教育 Agent 项目？", web_search_requested=True).allowed is True
