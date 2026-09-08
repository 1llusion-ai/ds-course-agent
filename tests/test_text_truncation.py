import inspect

import pytest

import ds_course_agent.retrieval.service as retrieval_service
import ds_course_agent.shared.text as shared_text
import ds_course_agent.tools._shared as tool_shared
import ds_course_agent.tools.web_fetch as web_fetch
import ds_course_agent.tools.web_search as web_search
from ds_course_agent.shared.text import truncate_text


@pytest.mark.parametrize(
    ("limit", "expected", "truncated"),
    [
        (-1, "", True),
        (0, "", True),
        (1, "a", True),
        (2, "ab", True),
        (3, "abc", True),
        (4, "a...", True),
        (6, "abcdef", False),
    ],
)
def test_shared_truncate_text_enforces_tiny_and_zero_budgets(limit, expected, truncated):
    result, was_truncated = truncate_text("abcdef", limit)

    assert result == expected
    assert was_truncated is truncated
    assert len(result) <= max(limit, 0)


def test_shared_truncate_text_supports_dynamic_markers_and_whitespace_policy():
    marker_calls = []

    def marker(original_chars, limit):
        marker_calls.append((original_chars, limit))
        return f"<{original_chars}/{limit}>"

    result, was_truncated = truncate_text(
        "abcdefghij",
        7,
        marker=marker,
        strip_whitespace=False,
    )

    assert result == "a<10/7>"
    assert len(result) <= 7
    assert was_truncated is True
    assert marker_calls == [(10, 7)]
    assert truncate_text("  abc  ", 10, strip_whitespace=False) == ("  abc  ", False)


def test_generic_character_budget_has_one_shared_owner_without_wrappers():
    assert truncate_text.__module__ == "ds_course_agent.shared.text"
    assert sum(name == "truncate_text" and inspect.isfunction(value) for name, value in vars(shared_text).items()) == 1
    assert not hasattr(retrieval_service, "_truncate_text")
    assert not hasattr(tool_shared, "truncate_text")
    assert not hasattr(tool_shared, "truncate_text_only")
    assert not hasattr(web_fetch, "_truncate")
    assert not hasattr(web_search, "_truncate")
