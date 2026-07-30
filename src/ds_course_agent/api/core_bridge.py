"""
桥接 ds_course_agent.rag 模块与 FastAPI
"""

import logging
import os
import uuid
from collections.abc import Iterator

try:
    import certifi
except ImportError:  # pragma: no cover - requests usually installs certifi
    certifi = None


def _configure_ssl_cert_path() -> None:
    """Prefer a portable CA bundle when the environment does not set one."""

    if os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"):
        return
    if certifi is None:
        return

    cert_path = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", cert_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_path)


# 修复SSL证书路径（必须在导入其他模块前设置）
_configure_ssl_cert_path()

from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
    logger.info("Loaded .env from %s", _env_path)

_agent_service = None
_memory_core = None


def get_memory_core():
    global _memory_core
    if _memory_core is None:
        from ds_course_agent.rag.memory_core import get_memory_core as _get_core

        _memory_core = _get_core()
    return _memory_core


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        from ds_course_agent.rag.agent import get_agent_service as _get_service

        _agent_service = _get_service()
    return _agent_service


def chat_with_history(message: str, session_id: str, student_id: str, web_search: bool = False) -> dict:
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace, trace_error, trace_span
    from ds_course_agent.tools.course_rag import begin_retrieval_trace, end_retrieval_trace

    q_token = begin_query_trace(
        meta={
            "session_id": session_id,
            "student_id": student_id,
            "web_search": bool(web_search),
        }
    )
    token = begin_retrieval_trace()

    try:
        with trace_span("core_bridge.get_agent_service"):
            service = get_agent_service()
        with trace_span("core_bridge.agent_chat"):
            kwargs = {
                "user_input": message,
                "session_id": session_id,
                "student_id": student_id,
            }
            # Preserve backward-compatible call signatures for tests and older
            # service implementations unless the explicit web-search switch is on.
            if web_search:
                kwargs["web_search"] = True
            execution_result = service.chat_with_history(**kwargs)
            content = execution_result.content
    except Exception as e:
        logger.error("Agent调用出错: %s", e, exc_info=True)
        trace_error("core_bridge.chat", e)
        end_query_trace(q_token, status="error")
        raise
    finally:
        end_retrieval_trace(token)

    q_trace = end_query_trace(q_token, status="error" if not content else "ok")
    logger.info("QueryTrace: %s", q_trace)

    return {
        "content": content,
        "used_retrieval": execution_result.used_retrieval,
        "sources": execution_result.sources,
        "family": execution_result.family.value,
        "intent": execution_result.intent.value,
        "execution_mode": execution_result.execution_mode.value,
        "degraded": execution_result.degraded,
        "query_trace": q_trace,
    }


def stream_chat_with_history(message: str, session_id: str, student_id: str, web_search: bool = False):
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace, trace_error, trace_span
    from ds_course_agent.tools.course_rag import begin_retrieval_trace, end_retrieval_trace

    q_token = begin_query_trace(
        meta={
            "session_id": session_id,
            "student_id": student_id,
            "web_search": bool(web_search),
        }
    )
    token = begin_retrieval_trace()
    final_content = ""
    accumulated_content = ""
    stream_id = None
    final_family = None
    final_intent = None
    final_execution_mode = None
    stream_error: str | None = None

    try:
        with trace_span("core_bridge.get_agent_service"):
            service = get_agent_service()
        with trace_span("core_bridge.agent_stream"):
            kwargs = {
                "user_input": message,
                "session_id": session_id,
                "student_id": student_id,
            }
            if web_search:
                kwargs["web_search"] = True
            for event in service.stream_chat_with_history(**kwargs):
                event_type = event.get("type")
                if event_type == "delta":
                    accumulated_content += str(event.get("delta") or "")
                    yield event
                elif event_type == "progress":
                    yield event
                elif event_type == "done":
                    final_content = event.get("content", "") or accumulated_content
                    stream_id = event.get("stream_id")
                    final_family = event.get("family")
                    final_intent = event.get("intent")
                    final_execution_mode = event.get("execution_mode")
    except Exception as e:
        logger.error("流式Agent调用出错: %s", e, exc_info=True)
        trace_error("core_bridge.stream", e)
        stream_error = f"流式调用出错：{str(e)[:100]}"
        final_content = accumulated_content
    finally:
        trace = end_retrieval_trace(token)

    q_trace = end_query_trace(q_token, status="error" if stream_error or not final_content else "ok")
    logger.info("QueryTrace: %s", q_trace)

    final_event = {
        "type": "final",
        "content": final_content,
        "used_retrieval": trace.used_retrieval,
        "sources": trace.sources,
        "query_trace": q_trace,
        "stream_id": stream_id,
        "family": final_family,
        "intent": final_intent,
        "execution_mode": final_execution_mode,
    }
    if stream_error:
        final_event["error"] = stream_error
        if not final_content:
            final_event["content"] = f'关于"{message}"的问题，我需要查阅课程资料后才能回答。\n\n（{stream_error}）'
    yield final_event


def stream_continue_with_history(
    partial_content: str,
    session_id: str,
    student_id: str,
) -> Iterator[dict]:
    """Continue an interrupted assistant answer without adding a visible user turn."""

    from langchain_core.messages import AIMessage

    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace, trace_error, trace_span
    from ds_course_agent.shared.history import get_history

    stream_id = uuid.uuid4().hex
    continuation_parts: list[str] = []
    stream_error: str | None = None
    q_token = begin_query_trace(
        meta={
            "session_id": session_id,
            "student_id": student_id,
            "continuation": True,
        }
    )

    yield {
        "type": "progress",
        "phase": "generation",
        "message": "正在继续生成...",
        "stream_id": stream_id,
        "resuming": False,
    }

    try:
        with trace_span("core_bridge.get_agent_service"):
            service = get_agent_service()
        history = get_history(session_id)
        transient_history = list(history.messages)
        if partial_content:
            transient_history.append(AIMessage(content=partial_content))

        turn_context = (
            "你正在续写一条被用户主动停止的回答。对话历史中最后一条 assistant 内容"
            "是用户已经看到的部分。只输出尚未输出的后续内容，与断点自然衔接；"
            "不要重复已有内容，不要重新开头，也不要提及停止、续写或这些指令。"
        )
        with trace_span("core_bridge.agent_continue_stream"):
            for chunk in service.direct_chat(
                "继续完成上一条回答。",
                transient_history,
                stream=True,
                turn_context=turn_context,
            ):
                text = str(chunk or "")
                if not text:
                    continue
                continuation_parts.append(text)
                yield {
                    "type": "delta",
                    "delta": text,
                    "stream_id": stream_id,
                    "resuming": False,
                }
    except Exception as exc:
        logger.error("续写Agent调用出错: %s", exc, exc_info=True)
        trace_error("core_bridge.continue_stream", exc)
        stream_error = f"续写调用出错：{str(exc)[:100]}"

    continuation = "".join(continuation_parts)
    final_content = f"{partial_content}{continuation}"
    if final_content:
        try:
            get_history(session_id).add_messages([AIMessage(content=final_content)])
        except Exception as exc:
            logger.error("续写结果写入历史失败: %s", exc, exc_info=True)
            trace_error("core_bridge.continue_history", exc)
            stream_error = stream_error or f"续写历史保存失败：{str(exc)[:100]}"

    q_trace = end_query_trace(q_token, status="error" if stream_error else "ok")
    final_event = {
        "type": "final",
        "content": final_content,
        "used_retrieval": False,
        "sources": [],
        "query_trace": q_trace,
        "stream_id": stream_id,
    }
    if stream_error:
        final_event["error"] = stream_error
    yield final_event
