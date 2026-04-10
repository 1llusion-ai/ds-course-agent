# 先加载环境变量
from app.core_bridge import PROJECT_ROOT
from dotenv import load_dotenv
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from typing import AsyncGenerator
from datetime import datetime
import asyncio

from app.schemas.chat import ChatRequest, ChatResponse, ChatMessage, ChatHistoryResponse
from app.core_bridge import chat_with_history
from app.state import _chat_history, _save as _save_state

router = APIRouter()


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


def _build_sources(question: str):
    """基于 RAG 检索构建来源列表供前端展示"""
    try:
        from core.tools import get_rag_service, _get_absolute_page
        import os
        import re

        service = get_rag_service()
        result = service.retrieve(question)
        sources = []
        for doc in result.documents:
            source = doc.metadata.get("source", "未知来源")
            chapter = doc.metadata.get("chapter", "")
            abs_page = _get_absolute_page(doc)

            match = re.search(r'第(\d+)章', source)
            chapter_num = f"第{match.group(1)}章" if match else ""

            if chapter:
                if abs_page and chapter_num:
                    ref = f"《{chapter_num} {chapter}》第{abs_page}页"
                elif chapter_num:
                    ref = f"《{chapter_num} {chapter}》"
                else:
                    ref = f"《{chapter}》"
            else:
                ref = os.path.basename(source)

            if ref not in [s["reference"] for s in sources]:
                sources.append({"reference": ref})
        return sources
    except Exception:
        return []


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    """发送消息（调用真实 Agent）"""
    # 保存用户消息
    user_msg = ChatMessage(role="user", content=data.message)
    if data.session_id not in _chat_history:
        _chat_history[data.session_id] = []
    _chat_history[data.session_id].append(_msg_to_dict(user_msg))
    _save_state()

    try:
        # 调用真实 Agent 生成回答
        assistant_content = await run_in_threadpool(
            chat_with_history,
            message=data.message,
            session_id=data.session_id,
            student_id=data.student_id
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 清理已添加的用户消息
        _chat_history[data.session_id].pop()
        _save_state()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "AGENT_ERROR",
                "message": f"Agent处理失败: {str(e)}",
                "session_id": data.session_id
            }
        )

    sources = _build_sources(data.message)
    assistant_msg = ChatMessage(role="assistant", content=assistant_content, sources=sources)
    _chat_history[data.session_id].append(_msg_to_dict(assistant_msg))
    _save_state()

    # 更新会话的元数据（消息数和时间）
    from app.state import _sessions
    if data.session_id in _sessions:
        _sessions[data.session_id]["message_count"] = len(_chat_history[data.session_id])
        _sessions[data.session_id]["updated_at"] = datetime.now().isoformat()
        _save_state()

    return ChatResponse(message=assistant_msg, session_id=data.session_id)


@router.get("/send/stream")
async def send_message_stream(
    session_id: str,
    message: str,
    student_id: str = "default_student"
):
    """发送消息（流式/SSE）

    使用 GET 方法支持 EventSource (SSE)
    """
    async def generate() -> AsyncGenerator[str, None]:
        if session_id not in _chat_history:
            _chat_history[session_id] = []
        _chat_history[session_id].append(_msg_to_dict(ChatMessage(role="user", content=message)))
        _save_state()

        # 模拟流式回复
        words = f"这是关于「{message}」的回答。我会逐步输出，模拟真实的打字机效果。"
        response_words = []

        for word in words:
            response_words.append(word)
            yield f"data: {''.join(response_words)}\n\n"
            await asyncio.sleep(0.05)

        full_response = "".join(response_words)
        _chat_history[session_id].append(_msg_to_dict(ChatMessage(role="assistant", content=full_response)))
        _save_state()

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str, student_id: str = "default_student"):
    """获取会话聊天记录

    需要校验 session 归属 student_id
    """
    from app.state import _sessions
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    raw_messages = _chat_history.get(session_id, [])
    messages = [_msg_from_dict(m) for m in raw_messages]
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        total=len(messages)
    )


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str):
    """清空聊天记录"""
    if session_id in _chat_history:
        del _chat_history[session_id]
        _save_state()
    return {"message": "聊天记录已清空"}
