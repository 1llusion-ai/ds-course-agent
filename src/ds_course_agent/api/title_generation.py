"""Utilities for generating concise, readable chat session titles.

The LLM is still the preferred title generator, but these helpers make sure
that failed/low-quality generations do not fall back to a raw character slice
of the user's first question.
"""

from __future__ import annotations

import re


DEFAULT_SESSION_TITLE = "新会话"
SESSION_TITLE_MAX_CHARS = 18
LEGACY_SESSION_TITLE_MAX_CHARS = 10

_TRAILING_PUNCTUATION = " \t\r\n，,。.!！?？：:；;、-—_"
_QUESTION_MARKERS = (
    "为什么",
    "是什么",
    "是啥",
    "有哪些",
    "有什么",
    "怎么",
    "如何",
    "能不能",
    "能否",
    "可以",
    "请问",
    "吗",
    "？",
    "?",
)


def _strip_wrapping_quotes(text: str) -> str:
    quote_pairs = {
        '"': '"',
        "'": "'",
        "“": "”",
        "‘": "’",
        "「": "」",
        "『": "』",
        "《": "》",
    }
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for left, right in quote_pairs.items():
            if text.startswith(left) and text.endswith(right):
                text = text[1:-1].strip()
                changed = True
                break
    return text


def _normalize_title_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Remove spaces between Chinese characters, but preserve useful separators
    # such as "Python 交叉验证" or "K-means 基本步骤".
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，,。.!！?？：:；;、])", r"\1", text)
    text = re.sub(r"([（(])\s+", r"\1", text)
    text = re.sub(r"\s+([）)])", r"\1", text)
    return text.strip()


def _normalize_for_compare(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[，,。.!！?？：:；;、'\"“”‘’「」『』《》()（）\[\]【】\-—_]", "", text)


def _truncate_title(title: str, max_chars: int = SESSION_TITLE_MAX_CHARS) -> str:
    title = _normalize_title_spacing(title).strip(_TRAILING_PUNCTUATION)
    if len(title) <= max_chars:
        return title
    return title[:max_chars].rstrip(_TRAILING_PUNCTUATION)


def _remove_leading_request_words(text: str) -> str:
    patterns = [
        r"^(请问|请你|请帮我|麻烦你|麻烦|帮我|帮忙|能不能|能否|可以|可不可以|你能不能|你能否|你可以|我想|给我)\s*",
        r"^(解释一下|解释|说明一下|说明|讲一下|讲讲|介绍一下|介绍|分析一下|分析|演示一下|演示)\s*",
        r"^(一个|一次|一下)\s*",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            next_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            if next_text != text:
                text = next_text
                changed = True
    return text


def _compact_question_text(question: str) -> str:
    text = str(question or "").strip()
    text = re.sub(r"[\r\n]+", " ", text)
    text = _normalize_title_spacing(text)
    text = text.strip(_TRAILING_PUNCTUATION)
    text = _remove_leading_request_words(text)
    text = re.sub(r"^(请用)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(一下|一个|一次)$", "", text).strip()
    return text.strip(_TRAILING_PUNCTUATION)


def _fallback_by_pattern(text: str) -> str | None:
    if not text:
        return None

    def join_topic_suffix(topic: str, suffix: str) -> str:
        topic = topic.strip(_TRAILING_PUNCTUATION)
        if not topic:
            return suffix
        if re.search(r"[A-Za-z0-9]$", topic) and re.search(r"^[\u4e00-\u9fff]", suffix):
            return f"{topic} {suffix}"
        return f"{topic}{suffix}"

    week_match = re.search(r"第[一二三四五六七八九十百0-9]+周", text)
    if week_match and re.search(r"(几号|什么时候|时间|安排|内容|上什么)", text):
        return f"{week_match.group(0)}课程时间"

    if re.search(r"(下一节课|下节课|下堂课)", text) and re.search(r"(什么时候|几号|时间|安排)", text):
        return "下节课时间"

    if re.search(r"(今天|今日).*(新闻|资讯|消息)", text):
        return "今日新闻"

    if re.search(r"Python.*交叉验证|交叉验证.*Python", text, flags=re.IGNORECASE):
        if re.search(r"(演示|代码|实现|示例)", text):
            return "Python 交叉验证演示"
        return "Python 交叉验证"

    match = re.search(r"(?:区分|区别|比较)\s*(.+?)\s*(?:和|与|vs|VS|/)\s*(.+)$", text)
    if match:
        left = match.group(1).strip(_TRAILING_PUNCTUATION)
        right = re.sub(r"(的)?(区别|差异|不同|比较)$", "", match.group(2)).strip(_TRAILING_PUNCTUATION)
        if left and right:
            return f"{left}与{right}区分"

    match = re.search(r"(.+?)\s*(?:和|与|vs|VS|/)\s*(.+?)(?:的)?(?:区别|差异|不同|比较)$", text)
    if match:
        left = match.group(1).strip(_TRAILING_PUNCTUATION)
        right = match.group(2).strip(_TRAILING_PUNCTUATION)
        if left and right:
            return f"{left}与{right}区分"

    if re.search(r"(学习)?路径|路线|计划|推荐", text):
        topic = ""
        match = re.search(r"(?:推荐)?(?:一个|一条|一份)?(?:学习)?(.+?)(?:的)?(?:学习)?(?:路径|路线|计划)", text)
        if match:
            topic = match.group(1)
        topic = topic or text
        topic = re.sub(r"^(推荐|给我推荐|一个|一条|一份|学习)\s*", "", topic)
        topic = re.sub(r"(的)?(学习)?(路径|路线|计划|推荐).*$", "", topic).strip()
        topic = re.sub(r"^(一个|一条|一份|学习)", "", topic).strip()
        if topic:
            return join_topic_suffix(topic, "路径推荐")

    match = re.search(r"(.+?)为什么(?:能|可以|会)?(.+)$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        rest = re.sub(r"^(做|进行|完成|用于)", "", match.group(2)).strip(_TRAILING_PUNCTUATION)
        if topic and rest:
            if re.search(r"(分类|预测|回归|聚类)", rest):
                return join_topic_suffix(topic, f"{rest}原理")
            return join_topic_suffix(topic, "原因")

    match = re.search(r"(.+?)(?:的)?(?:基本)?(?:步骤|流程)(?:是什么|有哪些|是啥)?$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        if topic:
            suffix = "基本步骤" if "基本" in text else "步骤"
            return join_topic_suffix(topic, suffix)

    match = re.search(r"(.+?)(?:有哪些|有什么)(方法|类型|类别|内容|工具|案例)?$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        suffix = match.group(2) or "梳理"
        if topic:
            return join_topic_suffix(topic, suffix)

    match = re.search(r"(.+?)(?:有哪些|有什么|包括哪些|包含哪些)$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        if topic:
            return join_topic_suffix(topic, "梳理")

    match = re.search(r"(.+?)(?:是什么|是啥|指什么)$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        if topic:
            if re.search(r"(步骤|流程|方法)$", topic):
                return topic
            return join_topic_suffix(topic, "概念")

    match = re.search(r"(?:怎么|如何)(.+)$", text)
    if match:
        topic = match.group(1).strip(_TRAILING_PUNCTUATION)
        if topic:
            return join_topic_suffix(topic, "方法")

    return None


def _remove_question_fillers(text: str) -> str:
    replacements = [
        (r"(请问|请|帮我|给我|能不能|能否|可以|麻烦)", ""),
        (r"(解释一下|解释|说明一下|说明|讲一下|讲讲|介绍一下|介绍)", ""),
        (r"(为什么|是什么|是啥|有哪些|有什么|怎么|如何|吗)$", ""),
        (r"(一下|一个|一次|基本)$", ""),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE).strip()
    return text.strip(_TRAILING_PUNCTUATION)


def build_fallback_session_title(question: str, max_chars: int = SESSION_TITLE_MAX_CHARS) -> str:
    """Build a deterministic title when LLM title generation is unavailable.

    This intentionally tries to create a topic-like phrase instead of slicing the
    first N characters of the question.
    """

    compact = _compact_question_text(question)
    patterned = _fallback_by_pattern(compact)
    if patterned:
        return _truncate_title(patterned, max_chars) or DEFAULT_SESSION_TITLE

    fallback = _remove_question_fillers(compact)
    fallback = fallback.replace(" vs ", "与").replace(" VS ", "与")
    fallback = fallback.replace("和", "与") if re.search(r"(区别|差异|比较|区分)", fallback) else fallback
    return _truncate_title(fallback, max_chars) or DEFAULT_SESSION_TITLE


def _looks_like_question_prefix(question: str, title: str) -> bool:
    question_norm = _normalize_for_compare(question)
    title_norm = _normalize_for_compare(title)
    if not question_norm or not title_norm:
        return False
    if not question_norm.startswith(title_norm):
        return False
    return len(question_norm) > len(title_norm) and len(title_norm) <= LEGACY_SESSION_TITLE_MAX_CHARS + 2


def looks_like_unprocessed_question_title(question: str, title: str) -> bool:
    """Return True if a stored/generated title looks like the raw question."""

    title = str(title or "").strip()
    if not title or title == DEFAULT_SESSION_TITLE:
        return True
    if _looks_like_question_prefix(question, title):
        return True
    if title.endswith(("？", "?")):
        return True
    return any(marker in title for marker in _QUESTION_MARKERS)


def should_repair_stored_title(question: str, title: str, title_source: str | None = None) -> bool:
    """Whether a persisted title should be repaired without an LLM call."""

    if title_source == "manual":
        return False
    if not str(question or "").strip():
        return False
    if not str(title or "").strip() or title == DEFAULT_SESSION_TITLE:
        return True
    if title_source in {"fallback", "heuristic", "llm_failed"}:
        return False
    return looks_like_unprocessed_question_title(question, title)


def _clean_generated_title(raw: str) -> str:
    """Clean common LLM title wrappers while preserving useful spacing."""

    title = str(raw or "").strip()
    if not title:
        return ""

    # Prefer the first meaningful line if the model returns a list or sentence.
    lines = [line.strip() for line in title.splitlines() if line.strip()]
    if lines:
        title = lines[0]

    while True:
        new_title = title
        new_title = re.sub(r"^\s*[-*•]\s*", "", new_title)
        new_title = re.sub(r"^\s*\d+[.、]\s*", "", new_title)
        for prefix in ["会话标题：", "会话标题:", "标题：", "标题:", "标题", "主题：", "主题:"]:
            if new_title.startswith(prefix):
                new_title = new_title[len(prefix):].strip()
                break
        if new_title == title:
            break
        title = new_title

    title = _strip_wrapping_quotes(title)
    title = title.strip(_TRAILING_PUNCTUATION)
    return _normalize_title_spacing(title)


def _finalize_title(question: str, raw_title: str, max_chars: int = SESSION_TITLE_MAX_CHARS) -> str:
    """Post-process generated title and repair low-quality raw-question slices."""

    title = _clean_generated_title(raw_title)
    fallback = build_fallback_session_title(question, max_chars=max_chars)
    if not title:
        return fallback

    # If the model simply copied/truncated the question, prefer the deterministic
    # topic phrase.
    if looks_like_unprocessed_question_title(question, title):
        return fallback

    week_match = re.search(r"第[一二三四五六七八九十百0-9]+周", question or "")
    if week_match and not re.search(r"第[一二三四五六七八九十百0-9]+周", title):
        title = f"{week_match.group(0)}{title}"

    return _truncate_title(title, max_chars) or fallback
