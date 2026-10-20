"""Copyright references in textbook content must not truncate a page."""

import pytest

from ds_course_agent.kb.cleaner import clean_text, remove_headers_footers_safe


@pytest.mark.parametrize(
    "text, heading",
    [
        (
            "表1-2 联合国数字素养全球框架\nDigital content creation\n"
            "3.3 Copyright and licenses 3.4 Programming\n"
            "1.2.3 数字素养教育 应知应会\n数字素养教育的正文。",
            "1.2.3 数字素养教育",
        ),
        (
            "4.3.1 数字版权与许可 应知应会\n版权(Copyright)，权利包括复制权、发行权。\n"
            "版权是创作者对其作品的专有权利。\n"
            "4.3.2 数字沟通礼仪 应知应会\n数字沟通礼仪的正文。",
            "4.3.2 数字沟通礼仪",
        ),
    ],
)
def test_real_textbook_copyright_mentions_keep_later_headings(text, heading):
    cleaned, _ = clean_text(text)
    assert heading in cleaned
    assert "正文。" in cleaned
    assert "Copyright" in cleaned


@pytest.mark.parametrize(
    "line",
    [
        "版权所有者享有复制权，后续内容需要保留。",
        "版权所有，是指作者依法享有的权利。下文继续讨论版权。",
        "正文引用：版权所有，侵权必究。",
        "Copyright law protects original works.",
        "The phrase All rights reserved is a copyright notice.",
        "All rights reserved 这句话常见于版权声明。",
    ],
)
def test_inline_chinese_and_english_copyright_discussion_is_retained(line):
    text = line + "\n接下来的小节正文。"
    cleaned, removed = remove_headers_footers_safe(text)
    assert cleaned == text
    assert removed == 0


@pytest.mark.parametrize(
    "footer", ["版权所有", "版权所有，侵权必究", "Copyright © 2026 Publisher", "All rights reserved."]
)
def test_independent_copyright_footer_removes_only_that_line(footer):
    text = "正文之前。\n" + footer + "\n正文之后。"
    cleaned, removed = remove_headers_footers_safe(text)
    assert footer not in cleaned
    assert "正文之前。" in cleaned
    assert "正文之后。" in cleaned
    assert removed == len(footer)
