from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse, ChatMessage, ChatHistoryResponse
from app.core_bridge import chat_with_history, get_memory_core

router = APIRouter()
_chat_history: dict = {}


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    """发送消息（调用真实 Agent）"""
    try:
        # 调用真实 Agent
        response_text = chat_with_history(
            message=data.message,
            session_id=data.session_id,
            student_id=data.student_id
        )

        # 记录消息
        if data.session_id not in _chat_history:
            _chat_history[data.session_id] = []

        _chat_history[data.session_id].append(
            ChatMessage(role="user", content=data.message)
        )
        assistant_msg = ChatMessage(role="assistant", content=response_text)
        _chat_history[data.session_id].append(assistant_msg)

        return ChatResponse(message=assistant_msg, session_id=data.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """获取聊天历史"""
    messages = _chat_history.get(session_id, [])
    return ChatHistoryResponse(session_id=session_id, messages=messages)


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str):
    """清除聊天历史"""
    if session_id in _chat_history:
        del _chat_history[session_id]
    return {"message": "历史记录已清除", "session_id": session_id}
