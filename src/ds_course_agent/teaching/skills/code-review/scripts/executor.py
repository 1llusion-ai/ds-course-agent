"""Code review skill executor.

Reviews student code: locates errors, explains why they are wrong, and provides
corrected code. Used when a student pastes code and asks "is this correct?" or
"where is the bug?".
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure `ds_course_agent` is importable when this module is loaded directly.
_SRC_DIR = Path(__file__).resolve().parents[5]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ds_course_agent.rag.code_executor import (  # noqa: E402
    PythonSandbox,
    extract_python_code,
    extract_question,
    format_python_execution_answer,
)


def _get_llm():
    from ds_course_agent.shared.llm import get_chat_model

    return get_chat_model()


def _call_llm(prompt: str) -> str:
    llm = _get_llm()
    response = llm.invoke(prompt)
    if hasattr(response, "content"):
        return response.content
    return str(response) if response else ""


class CodeReviewSkill:
    """Review student code and produce a teaching diagnosis + corrected code."""

    def execute(self, question: str, student_id: str, session_id: str) -> str:
        del student_id, session_id  # not used for now

        code = extract_python_code(question)
        user_question = extract_question(question) or "这段代码是否正确？"

        if not code:
            return (
                "没有检测到可审查的 Python 代码。"
                "请把代码放在 ```python ... ``` 代码块中，"
                "或直接贴出代码并告诉我你想问的问题。"
            )

        try:
            prompt = self._build_prompt(code, user_question)
            answer = _call_llm(prompt)
            if answer and answer.strip():
                return answer.strip()
        except Exception:
            pass  # fall through to execution fallback

        # LLM failed or returned empty: degrade to a raw execution transcript.
        try:
            result = PythonSandbox().execute(code)
            return format_python_execution_answer(code, result)
        except Exception as exc:
            return (
                "我在分析这段代码时遇到了问题，暂时无法给出诊断。"
                f"（错误：{str(exc)[:80]}）请稍后重试，"
                "或把代码放进 ```python``` 代码块后再发一次。"
            )

    def _build_prompt(self, code: str, user_question: str) -> str:
        return f"""你是一位《数据科学导论》课程的编程辅导教师。一位学生贴了一段 Python 代码并提出了问题。请仔细审查这段代码。

## 学生的代码
```python
{code}
```

## 学生的问题
{user_question}

## 你的任务
1. **逐行分析**：检查代码的逻辑、语法和常见错误（如比较运算符方向、缩进、变量名、循环条件、异常处理等）。
2. **定位错误**：如果发现问题，明确指出是第几行、哪一句，引用具体代码。
3. **解释原因**：说明为什么这里是错的，会造成什么后果。
4. **给出修正后的完整代码**：放在 ```python``` 代码块中，确保修正后能正确运行。
5. **如果代码完全正确**：确认它是对的，并简要说明这段代码做了什么。

## 回答格式
- 先用一句话总结：代码是否有问题、问题是什么。
- 然后逐条列出发现的问题（带行号和原因）。
- 最后给出修正后的完整代码，并用一两句话说明改了什么。

用中文回答，语气友好、鼓励学生思考。不要替学生直接完成作业，但要清楚指出错误并给出修正。"""


def execute(question: str, student_id: str, session_id: str) -> str:
    """Skill entrypoint."""
    return CodeReviewSkill().execute(question, student_id, session_id)
