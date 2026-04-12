from ..core_bridge import PROJECT_ROOT
from dotenv import load_dotenv
from pathlib import Path

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..core_bridge import chat_with_history, stream_chat_with_history
from ..schemas.chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse
from ..state import _chat_history, _save as _save_state, _sessions

router = APIRouter()

_STREAM_SENTINEL = object()

_title_gen_cache: dict[str, bool] = {}  # session_id -> title generated flag


async def _generate_session_title(question: str) -> str:
    """用 LLM 将问题概括为标题，限制 10 字以内。"""
    prompt = f"""请把下面这个问题概括成一个会话标题，必须满足以下要求：
1. 不超过 10 个字符（汉字、英文字母、数字均算 1 个字符）
2. 必须保留核心语义
3. 直接返回标题，不要任何解释或引号

问题：{question}

标题："""

    try:
        from core.agent import get_chat_model
        llm = get_chat_model()
        response = llm.invoke(prompt)
        title = ""
        if hasattr(response, "content"):
            title = response.content.strip()
        elif isinstance(response, str):
            title = response.strip()
        else:
            title = str(response).strip()
        # 截断到10字
        return title[:10]
    except Exception:
        # 降级：直接取前10字
        return question[:10]


def _msg_to_dict(msg: ChatMessage) -> dict:
    return {
        "role": msg.role,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
        "sources": msg.sources or None,
    }


def _msg_from_dict(data: dict) -> ChatMessage:
    ts = data.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ChatMessage(
        role=data.get("role", "assistant"),
        content=data.get("content", ""),
        timestamp=ts or datetime.now(),
        sources=data.get("sources"),
    )


def _ensure_session_history(session_id: str) -> None:
    if session_id not in _chat_history:
        _chat_history[session_id] = []


def _append_message(session_id: str, message: ChatMessage) -> None:
    _ensure_session_history(session_id)
    _chat_history[session_id].append(_msg_to_dict(message))
    _save_state()


def _update_session_metadata(session_id: str, timestamp: str | None = None) -> None:
    if session_id not in _sessions:
        return

    _sessions[session_id]["message_count"] = len(_chat_history.get(session_id, []))
    _sessions[session_id]["updated_at"] = timestamp or datetime.now().isoformat()
    _save_state()


def _build_stream_error_message(text: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=f"⚠️ {text}",
        timestamp=datetime.now(),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    # 判断是否首次消息
    is_first_message = len(_chat_history.get(data.session_id, [])) == 0

    user_msg = ChatMessage(role="user", content=data.message)
    _append_message(data.session_id, user_msg)

    # 首次消息：LLM 生成标题
    if is_first_message:
        generated_title = await _generate_session_title(data.message)
        if data.session_id in _sessions:
            _sessions[data.session_id]["title"] = generated_title
            _save_state()

    try:
        assistant_result = await run_in_threadpool(
            chat_with_history,
            message=data.message,
            session_id=data.session_id,
            student_id=data.student_id,
        )
    except Exception as exc:
        import traceback

        traceback.print_exc()
        _chat_history[data.session_id].pop()
        _save_state()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "AGENT_ERROR",
                "message": f"Agent处理失败: {str(exc)}",
                "session_id": data.session_id,
            },
        ) from exc

    assistant_content = assistant_result.get("content", "") if isinstance(assistant_result, dict) else str(assistant_result)
    assistant_sources = assistant_result.get("sources") if isinstance(assistant_result, dict) else None

    assistant_msg = ChatMessage(
        role="assistant",
        content=assistant_content,
        sources=assistant_sources or None,
    )
    _append_message(data.session_id, assistant_msg)
    _update_session_metadata(data.session_id, assistant_msg.timestamp.isoformat())

    return ChatResponse(message=assistant_msg, session_id=data.session_id)


@router.get("/send/stream")
async def send_message_stream(
    session_id: str,
    message: str,
    student_id: str = "default_student",
):
    # 判断是否首次消息
    is_first_message = len(_chat_history.get(session_id, [])) == 0

    user_msg = ChatMessage(role="user", content=message)
    _append_message(session_id, user_msg)

    # 首次消息：LLM 生成标题
    if is_first_message:
        generated_title = await _generate_session_title(message)
        if session_id in _sessions:
            _sessions[session_id]["title"] = generated_title
            _save_state()

    async def generate() -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | object] = asyncio.Queue()

        def worker():
            try:
                for event in stream_chat_with_history(
                    message=message,
                    session_id=session_id,
                    student_id=student_id,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "error",
                        "message": f"流式响应失败: {str(exc)}",
                    },
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _STREAM_SENTINEL)

        worker_task = asyncio.create_task(run_in_threadpool(worker))
        final_sent = False

        try:
            while True:
                event = await queue.get()

                if event is _STREAM_SENTINEL:
                    break

                event_type = event.get("type")
                if event_type == "delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield _sse({"type": "delta", "delta": delta})
                    continue

                if event_type == "final":
                    final_sent = True
                    assistant_msg = ChatMessage(
                        role="assistant",
                        content=event.get("content", ""),
                        sources=event.get("sources") or None,
                    )
                    _append_message(session_id, assistant_msg)
                    _update_session_metadata(session_id, assistant_msg.timestamp.isoformat())
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    break

                if event_type == "error":
                    assistant_msg = _build_stream_error_message(event.get("message", "发送失败"))
                    _append_message(session_id, assistant_msg)
                    _update_session_metadata(session_id, assistant_msg.timestamp.isoformat())
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    final_sent = True
                    break

            if not final_sent:
                assistant_msg = _build_stream_error_message("流式连接已结束，但未收到完整回答。")
                _append_message(session_id, assistant_msg)
                _update_session_metadata(session_id, assistant_msg.timestamp.isoformat())
                yield _sse(
                    {
                        "type": "final",
                        "session_id": session_id,
                        "message": _msg_to_dict(assistant_msg),
                    }
                )
        finally:
            await worker_task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str, student_id: str = "default_student"):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    raw_messages = _chat_history.get(session_id, [])
    messages = [_msg_from_dict(item) for item in raw_messages]
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        total=len(messages),
    )


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str):
    if session_id in _chat_history:
        del _chat_history[session_id]
        _save_state()
    return {"message": "聊天记录已清空"}
