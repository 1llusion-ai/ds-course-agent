# RAG 课程助教系统 - 生产化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Streamlit 应用改造为前后端分离架构，实现可部署的 MVP，并建立评估指标体系

**Architecture:** 
- 后端：FastAPI 提供 REST API 和 SSE 流式输出，复用现有 core/ 模块逻辑
- 前端：Vue3 + Element Plus 实现 ChatGPT 风格界面
- 数据：复用现有 ChromaDB 和文件存储，通过 API 抽象访问
- 部署：Docker Compose 单机部署

**Tech Stack:** FastAPI, Vue3, Element Plus, Pinia, Docker, pytest

---

## 文件结构规划

### 后端（backend/）
```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── sessions.py      # 会话管理 API
│   │   ├── chat.py          # 聊天 API (含 SSE)
│   │   └── profile.py       # 学习画像 API
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── session.py       # 会话数据模型
│   │   ├── chat.py          # 聊天数据模型
│   │   └── profile.py       # 画像数据模型
│   └── dependencies.py      # 依赖注入
├── tests/
│   ├── __init__.py
│   ├── test_sessions.py
│   ├── test_chat.py
│   └── conftest.py
├── Dockerfile
└── requirements.txt
```

### 前端（frontend/）
```
frontend/
├── src/
│   ├── components/
│   │   ├── ChatSidebar.vue      # 侧边栏会话列表
│   │   ├── ChatMessage.vue      # 单条消息组件
│   │   ├── ChatInput.vue        # 输入框组件
│   │   ├── ProfileCard.vue      # 学习画像卡片
│   │   └── ProfileDetail.vue    # 画像详情页
│   ├── views/
│   │   ├── ChatView.vue         # 主聊天页
│   │   └── ProfileView.vue      # 画像详情页
│   ├── stores/
│   │   ├── session.js           # 会话状态管理
│   │   ├── chat.js              # 聊天状态管理
│   │   └── profile.js           # 画像状态管理
│   ├── api/
│   │   ├── client.js            # axios 配置
│   │   ├── sessions.js          # 会话 API
│   │   ├── chat.js              # 聊天 API
│   │   └── profile.js           # 画像 API
│   ├── router/
│   │   └── index.js             # 路由配置
│   ├── App.vue
│   └── main.js
├── public/
├── package.json
├── vite.config.js
└── Dockerfile
```

### 评估体系（eval/ 扩展）
```
eval/
├── metrics/                     # 评估指标
│   ├── __init__.py
│   ├── retrieval.py             # 检索质量指标
│   ├── answer.py                # 回答质量指标
│   └── benchmark.py             # 基准测试
├── data/                        # 评测数据集
│   └── qa_pairs.json            # 问答对
├── scripts/
│   └── run_benchmark.py         # 运行基准测试
└── reports/                     # 评测报告输出
```

---

## 第一阶段：后端 API 开发

### Task 1: 后端项目初始化

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
# FastAPI
fastapi==0.109.0
uvicorn[standard]==0.27.0
sse-starlette==2.0.0

# 复用现有核心模块
python-multipart==0.0.6
pydantic==2.5.0

# 测试
pytest==7.4.0
pytest-asyncio==0.21.0
httpx==0.26.0

# CORS
python-jose[cryptography]==3.3.0
```

- [ ] **Step 2: 创建 FastAPI 主应用**

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.routers import sessions, chat, profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("🚀 启动 RAG 助教后端服务...")
    yield
    print("👋 关闭服务")


app = FastAPI(
    title="RAG 课程助教 API",
    description="智能课程助教系统后端 API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "rag-tutor-backend"}
```

- [ ] **Step 3: 创建测试配置**

```python
# backend/tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """提供测试客户端"""
    return TestClient(app)


@pytest.fixture
def sample_session():
    """提供测试会话数据"""
    return {
        "title": "测试会话",
        "student_id": "test_student_001"
    }
```

- [ ] **Step 4: 验证后端启动**

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

浏览器访问 `http://localhost:8000/health`，预期返回：
```json
{"status": "ok", "service": "rag-tutor-backend"}
```

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: initialize FastAPI backend with basic structure"
```

---

### Task 2: 会话管理 API

**Files:**
- Create: `backend/app/schemas/session.py`
- Create: `backend/app/routers/sessions.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_sessions.py`

- [ ] **Step 1: 定义会话 Schema**

```python
# backend/app/schemas/session.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class SessionCreate(BaseModel):
    """创建会话请求"""
    title: str = Field(default="新会话", min_length=1, max_length=100)
    student_id: str = Field(default="default_student")


class SessionResponse(BaseModel):
    """会话响应"""
    id: str
    title: str
    student_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionList(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int


class SessionUpdate(BaseModel):
    """更新会话请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=100)
```

- [ ] **Step 2: 实现会话路由（占位实现）**

```python
# backend/app/routers/sessions.py
from fastapi import APIRouter, HTTPException
from typing import List
from datetime import datetime
import uuid

from app.schemas.session import SessionCreate, SessionResponse, SessionList, SessionUpdate

router = APIRouter()

# 内存存储（后续改为文件存储）
_sessions: dict = {}


@router.post("", response_model=SessionResponse)
async def create_session(data: SessionCreate):
    """创建新会话"""
    session_id = str(uuid.uuid4())
    now = datetime.now()
    
    session = SessionResponse(
        id=session_id,
        title=data.title,
        student_id=data.student_id,
        created_at=now,
        updated_at=now,
        message_count=0
    )
    _sessions[session_id] = session
    return session


@router.get("", response_model=SessionList)
async def list_sessions(student_id: str = "default_student"):
    """获取会话列表"""
    sessions = [
        s for s in _sessions.values()
        if s.student_id == student_id
    ]
    # 按更新时间倒序
    sessions.sort(key=lambda x: x.updated_at, reverse=True)
    
    return SessionList(
        sessions=sessions,
        total=len(sessions)
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取单个会话"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _sessions[session_id]


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    del _sessions[session_id]
    return {"message": "会话已删除"}


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, data: SessionUpdate):
    """更新会话"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    session = _sessions[session_id]
    if data.title:
        session.title = data.title
    session.updated_at = datetime.now()
    return session
```

- [ ] **Step 3: 编写会话 API 测试**

```python
# backend/tests/test_sessions.py
def test_create_session(client):
    """测试创建会话"""
    response = client.post("/api/sessions", json={
        "title": "测试会话",
        "student_id": "student_001"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "测试会话"
    assert data["student_id"] == "student_001"
    assert "id" in data


def test_list_sessions(client):
    """测试获取会话列表"""
    # 先创建两个会话
    client.post("/api/sessions", json={"title": "会话1", "student_id": "student_001"})
    client.post("/api/sessions", json={"title": "会话2", "student_id": "student_001"})
    
    response = client.get("/api/sessions?student_id=student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["sessions"]) == 2


def test_get_session_not_found(client):
    """测试获取不存在的会话"""
    response = client.get("/api/sessions/nonexistent-id")
    assert response.status_code == 404


def test_delete_session(client):
    """测试删除会话"""
    # 创建会话
    create_resp = client.post("/api/sessions", json={"title": "待删除"})
    session_id = create_resp.json()["id"]
    
    # 删除
    delete_resp = client.delete(f"/api/sessions/{session_id}")
    assert delete_resp.status_code == 200
    
    # 验证已删除
    get_resp = client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 404
```

- [ ] **Step 4: 运行测试**

```bash
cd backend
pytest tests/test_sessions.py -v
```

预期：4 个测试全部通过

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: implement session management API with tests"
```

---

### Task 3: 聊天 API 与上下文恢复

**Files:**
- Create: `backend/app/schemas/chat.py`
- Create: `backend/app/routers/chat.py`
- Create: `backend/tests/test_chat.py`

- [ ] **Step 1: 定义聊天 Schema**

```python
# backend/app/schemas/chat.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Literal


class ChatMessage(BaseModel):
    """单条消息"""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    sources: Optional[List[dict]] = None  # 引用来源


class ChatRequest(BaseModel):
    """发送消息请求"""
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    student_id: str = Field(default="default_student")
    stream: bool = False


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    message: ChatMessage
    session_id: str


class ChatHistoryResponse(BaseModel):
    """聊天记录响应"""
    session_id: str
    messages: List[ChatMessage]
    total: int
```

- [ ] **Step 2: 实现聊天路由（基础版）**

```python
# backend/app/routers/chat.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import asyncio

from app.schemas.chat import ChatRequest, ChatResponse, ChatMessage, ChatHistoryResponse

router = APIRouter()

# 内存存储聊天记录（后续改为文件存储）
_chat_history: dict = {}


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    """发送消息（非流式）"""
    # TODO: 后续集成 core/agent.py
    
    # 保存用户消息
    user_msg = ChatMessage(role="user", content=data.message)
    if data.session_id not in _chat_history:
        _chat_history[data.session_id] = []
    _chat_history[data.session_id].append(user_msg)
    
    # 模拟 AI 回复（后续替换为真实 Agent）
    assistant_content = f"收到你的问题：{data.message}\n\n（这里将集成 RAG Agent 生成回答）"
    assistant_msg = ChatMessage(role="assistant", content=assistant_content)
    _chat_history[data.session_id].append(assistant_msg)
    
    return ChatResponse(
        message=assistant_msg,
        session_id=data.session_id
    )


@router.post("/send/stream")
async def send_message_stream(data: ChatRequest):
    """发送消息（流式/SSE）"""
    async def generate() -> AsyncGenerator[str, None]:
        # 保存用户消息
        if data.session_id not in _chat_history:
            _chat_history[data.session_id] = []
        _chat_history[data.session_id].append(
            ChatMessage(role="user", content=data.message)
        )
        
        # 模拟流式回复
        words = f"这是关于「{data.message}」的回答。我会逐步输出，模拟真实的打字机效果。"
        response_words = []
        
        for word in words:
            response_words.append(word)
            yield f"data: {''.join(response_words)}\n\n"
            await asyncio.sleep(0.05)
        
        # 保存完整回复
        full_response = "".join(response_words)
        _chat_history[data.session_id].append(
            ChatMessage(role="assistant", content=full_response)
        )
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """获取会话聊天记录"""
    messages = _chat_history.get(session_id, [])
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
    return {"message": "聊天记录已清空"}
```

- [ ] **Step 3: 编写聊天 API 测试**

```python
# backend/tests/test_chat.py
def test_send_message(client):
    """测试发送消息"""
    response = client.post("/api/chat/send", json={
        "session_id": "test-session-001",
        "message": "什么是SVM？",
        "student_id": "student_001"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["message"]["role"] == "assistant"
    assert "SVM" in data["message"]["content"]


def test_get_chat_history(client):
    """测试获取聊天记录"""
    # 发送一条消息
    client.post("/api/chat/send", json={
        "session_id": "test-session-002",
        "message": "测试问题",
        "student_id": "student_001"
    })
    
    # 获取历史
    response = client.get("/api/chat/history/test-session-002")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # 用户消息 + AI回复
    assert len(data["messages"]) == 2


def test_clear_chat_history(client):
    """测试清空聊天记录"""
    # 创建并清空
    client.post("/api/chat/send", json={
        "session_id": "test-session-003",
        "message": "测试",
    })
    
    response = client.delete("/api/chat/history/test-session-003")
    assert response.status_code == 200
    
    # 验证已清空
    history_resp = client.get("/api/chat/history/test-session-003")
    assert history_resp.json()["total"] == 0
```

- [ ] **Step 4: 运行测试**

```bash
cd backend
pytest tests/test_chat.py -v
```

预期：3 个测试全部通过

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: implement chat API with streaming support and tests"
```

---

### Task 4: 学习画像 API

**Files:**
- Create: `backend/app/schemas/profile.py`
- Create: `backend/app/routers/profile.py`
- Create: `backend/tests/test_profile.py`

- [ ] **Step 1: 定义画像 Schema**

```python
# backend/app/schemas/profile.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict


class ConceptFocus(BaseModel):
    """关注概念"""
    concept_id: str
    display_name: str
    mention_count: int
    chapter: Optional[str] = None
    last_mentioned: datetime


class WeakSpot(BaseModel):
    """薄弱点"""
    concept_id: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int


class LearningProgress(BaseModel):
    """学习进度"""
    current_chapter: Optional[str] = None
    total_interactions: int
    concepts_explored: int
    last_study_date: Optional[datetime] = None


class ProfileSummary(BaseModel):
    """画像摘要（聊天页显示）"""
    student_id: str
    recent_concepts: List[ConceptFocus]  # 最多显示 5 个
    weak_spots: List[WeakSpot]  # 置信度 > 0.5 的


class ProfileDetail(BaseModel):
    """画像详情（完整页面）"""
    student_id: str
    recent_concepts: List[ConceptFocus]
    weak_spots: List[WeakSpot]
    progress: LearningProgress
    chapter_stats: Dict[str, int]  # 章节 -> 互动次数
    daily_activity: Dict[str, int]  # 日期 -> 互动次数（最近30天）
```

- [ ] **Step 2: 实现画像路由（复用现有 core/memory_core.py）**

```python
# backend/app/routers/profile.py
from fastapi import APIRouter, HTTPException
from typing import List

from app.schemas.profile import (
    ProfileSummary, ProfileDetail, 
    ConceptFocus, WeakSpot, LearningProgress
)

router = APIRouter()

# TODO: 后续从 sys.path 导入现有 core 模块
# import sys
# sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
# from core.memory_core import get_memory_core


@router.get("/summary/{student_id}", response_model=ProfileSummary)
async def get_profile_summary(student_id: str):
    """获取画像摘要（用于聊天页）"""
    # TODO: 替换为真实数据
    return ProfileSummary(
        student_id=student_id,
        recent_concepts=[
            ConceptFocus(
                concept_id="svm",
                display_name="支持向量机",
                mention_count=5,
                chapter="第3章",
                last_mentioned=datetime.now()
            ),
            ConceptFocus(
                concept_id="gradient_descent",
                display_name="梯度下降",
                mention_count=3,
                chapter="第2章",
                last_mentioned=datetime.now()
            )
        ],
        weak_spots=[
            WeakSpot(
                concept_id="kernel_function",
                display_name="核函数",
                confidence=0.75,
                evidence_count=2
            )
        ]
    )


@router.get("/detail/{student_id}", response_model=ProfileDetail)
async def get_profile_detail(student_id: str):
    """获取完整画像详情"""
    # TODO: 替换为真实数据
    return ProfileDetail(
        student_id=student_id,
        recent_concepts=[
            ConceptFocus(
                concept_id="svm",
                display_name="支持向量机",
                mention_count=5,
                chapter="第3章",
                last_mentioned=datetime.now()
            )
        ],
        weak_spots=[
            WeakSpot(
                concept_id="kernel_function",
                display_name="核函数",
                confidence=0.75,
                evidence_count=2
            )
        ],
        progress=LearningProgress(
            current_chapter="第3章",
            total_interactions=42,
            concepts_explored=8,
            last_study_date=datetime.now()
        ),
        chapter_stats={"第1章": 5, "第2章": 12, "第3章": 15},
        daily_activity={"2026-04-01": 3, "2026-04-02": 5}
    )


@router.post("/aggregate/{student_id}")
async def aggregate_profile(student_id: str):
    """手动触发画像聚合"""
    # TODO: 调用 memory_core.aggregate_profile()
    return {"message": "画像已更新", "student_id": student_id}
```

- [ ] **Step 3: 编写画像 API 测试**

```python
# backend/tests/test_profile.py
def test_get_profile_summary(client):
    """测试获取画像摘要"""
    response = client.get("/api/profile/summary/student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "student_001"
    assert len(data["recent_concepts"]) > 0
    assert "weak_spots" in data


def test_get_profile_detail(client):
    """测试获取画像详情"""
    response = client.get("/api/profile/detail/student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "student_001"
    assert "progress" in data
    assert "chapter_stats" in data


def test_aggregate_profile(client):
    """测试触发画像聚合"""
    response = client.post("/api/profile/aggregate/student_001")
    assert response.status_code == 200
    assert response.json()["student_id"] == "student_001"
```

- [ ] **Step 4: 运行测试**

```bash
cd backend
pytest tests/test_profile.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: implement profile API with summary and detail endpoints"
```

---

### Task 5: 后端与现有核心模块集成

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/app/routers/profile.py`
- Create: `backend/app/core_bridge.py`

- [ ] **Step 1: 创建核心模块桥接器**

```python
# backend/app/core_bridge.py
"""
桥接现有 core/ 模块与 FastAPI
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 延迟导入，避免启动时加载
_agent_service = None
_memory_core = None


def get_agent_service():
    """获取 Agent 服务"""
    global _agent_service
    if _agent_service is None:
        from core.agent import get_agent_service as _get_service
        _agent_service = _get_service()
    return _agent_service


def get_memory_core():
    """获取记忆核心"""
    global _memory_core
    if _memory_core is None:
        from core.memory_core import get_memory_core as _get_core
        _memory_core = _get_core()
    return _memory_core


def chat_with_history(message: str, session_id: str, student_id: str) -> str:
    """调用 Agent 进行对话"""
    service = get_agent_service()
    return service.chat_with_history(
        user_input=message,
        session_id=session_id,
        student_id=student_id
    )
```

- [ ] **Step 2: 更新 chat.py 集成真实 Agent**

```python
# backend/app/routers/chat.py（关键修改）
import asyncio
from fastapi import APIRouter, HTTPException

# 延迟导入避免启动依赖
def get_bridge():
    from app.core_bridge import chat_with_history, get_memory_core
    return chat_with_history, get_memory_core


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    """发送消息（调用真实 Agent）"""
    chat_func, _ = get_bridge()
    
    try:
        # 调用真实 Agent
        response_text = chat_func(
            message=data.message,
            session_id=data.session_id,
            student_id=data.student_id
        )
        
        assistant_msg = ChatMessage(
            role="assistant", 
            content=response_text
        )
        
        return ChatResponse(
            message=assistant_msg,
            session_id=data.session_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: 更新 profile.py 集成真实记忆核心**

```python
# backend/app/routers/profile.py（关键修改）
from fastapi import APIRouter


def get_memory():
    from app.core_bridge import get_memory_core
    return get_memory_core()


@router.get("/summary/{student_id}", response_model=ProfileSummary)
async def get_profile_summary(student_id: str):
    """获取真实画像摘要"""
    memory_core = get_memory()
    
    # 触发聚合
    memory_core.aggregate_profile(student_id)
    profile = memory_core.get_profile(student_id)
    
    # 转换为 Schema
    recent_concepts = [
        ConceptFocus(
            concept_id=cid,
            display_name=cf.display_name,
            mention_count=cf.mention_count,
            chapter=cf.chapter,
            last_mentioned=datetime.now()  # TODO: 从事件提取
        )
        for cid, cf in list(profile.recent_concepts.items())[:5]
    ]
    
    weak_spots = [
        WeakSpot(
            concept_id=ws.concept_id,
            display_name=ws.display_name,
            confidence=ws.confidence,
            evidence_count=len(ws.evidence)
        )
        for ws in profile.weak_spot_candidates
        if ws.confidence > 0.5
    ]
    
    return ProfileSummary(
        student_id=student_id,
        recent_concepts=recent_concepts,
        weak_spots=weak_spots
    )
```

- [ ] **Step 4: 集成测试**

```bash
cd backend
# 确保现有向量数据库存在
python -c "from app.core_bridge import get_agent_service; print('Agent 加载成功')"

# 运行所有测试
pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat: integrate backend with existing core modules"
```

---

## 第二阶段：前端开发

### Task 6: 前端项目初始化

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "rag-tutor-frontend",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.0",
    "pinia": "^2.1.0",
    "element-plus": "^2.5.0",
    "axios": "^1.6.0",
    "@element-plus/icons-vue": "^2.3.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0",
    "sass": "^1.69.0"
  }
}
```

- [ ] **Step 2: 创建 Vite 配置**

```javascript
// frontend/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
```

- [ ] **Step 3: 创建入口 HTML**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>智能课程助教</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&family=Noto+Sans+SC:wght@300;400;500;600&display=swap" rel="stylesheet">
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

- [ ] **Step 4: 创建入口 JS**

```javascript
// frontend/src/main.js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
```

- [ ] **Step 5: 创建根组件**

```vue
<!-- frontend/src/App.vue -->
<template>
  <router-view />
</template>

<script setup>
</script>

<style>
/* 全局样式 */
@import './styles/main.scss';
</style>
```

- [ ] **Step 6: 安装依赖并验证**

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`，预期看到空白页面无报错

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: initialize Vue3 frontend with Element Plus"
```

---

### Task 7: API 客户端和路由

**Files:**
- Create: `frontend/src/api/client.js`
- Create: `frontend/src/api/sessions.js`
- Create: `frontend/src/api/chat.js`
- Create: `frontend/src/api/profile.js`
- Create: `frontend/src/router/index.js`

- [ ] **Step 1: 创建 Axios 客户端**

```javascript
// frontend/src/api/client.js
import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
client.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('[API Error]', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default client
```

- [ ] **Step 2: 创建会话 API 模块**

```javascript
// frontend/src/api/sessions.js
import client from './client'

export const sessionsApi = {
  // 创建会话
  create: (data) => client.post('/sessions', data),
  
  // 获取列表
  list: (studentId = 'default_student') => 
    client.get(`/sessions?student_id=${studentId}`),
  
  // 获取单个
  get: (id) => client.get(`/sessions/${id}`),
  
  // 更新
  update: (id, data) => client.patch(`/sessions/${id}`, data),
  
  // 删除
  delete: (id) => client.delete(`/sessions/${id}`)
}
```

- [ ] **Step 3: 创建聊天 API 模块**

```javascript
// frontend/src/api/chat.js
import client from './client'

export const chatApi = {
  // 发送消息（非流式）
  send: (data) => client.post('/chat/send', data),
  
  // 获取历史
  getHistory: (sessionId) => client.get(`/chat/history/${sessionId}`),
  
  // 清空历史
  clearHistory: (sessionId) => client.delete(`/chat/history/${sessionId}`),
  
  // 流式发送（返回 EventSource）
  sendStream: (data) => {
    const params = new URLSearchParams({
      session_id: data.session_id,
      message: data.message,
      student_id: data.student_id || 'default_student'
    })
    return new EventSource(`/api/chat/send/stream?${params}`)
  }
}
```

- [ ] **Step 4: 创建画像 API 模块**

```javascript
// frontend/src/api/profile.js
import client from './client'

export const profileApi = {
  // 获取摘要
  getSummary: (studentId) => 
    client.get(`/profile/summary/${studentId}`),
  
  // 获取详情
  getDetail: (studentId) => 
    client.get(`/profile/detail/${studentId}`),
  
  // 触发聚合
  aggregate: (studentId) => 
    client.post(`/profile/aggregate/${studentId}`)
}
```

- [ ] **Step 5: 创建路由配置**

```javascript
// frontend/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import ProfileView from '../views/ProfileView.vue'

const routes = [
  {
    path: '/',
    redirect: '/chat'
  },
  {
    path: '/chat',
    name: 'Chat',
    component: ChatView
  },
  {
    path: '/chat/:sessionId',
    name: 'ChatWithSession',
    component: ChatView
  },
  {
    path: '/profile',
    name: 'Profile',
    component: ProfileView
  },
  {
    path: '/profile/:studentId',
    name: 'ProfileDetail',
    component: ProfileView
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/ frontend/src/router/
git commit -m "feat: add API clients and router configuration"
```

---

### Task 8: Pinia Store 状态管理

**Files:**
- Create: `frontend/src/stores/session.js`
- Create: `frontend/src/stores/chat.js`
- Create: `frontend/src/stores/profile.js`

- [ ] **Step 1: 创建会话 Store**

```javascript
// frontend/src/stores/session.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { sessionsApi } from '../api/sessions'

export const useSessionStore = defineStore('session', () => {
  // State
  const sessions = ref([])
  const currentSessionId = ref(null)
  const loading = ref(false)
  
  // Getters
  const currentSession = computed(() => 
    sessions.value.find(s => s.id === currentSessionId.value)
  )
  
  const sortedSessions = computed(() => 
    [...sessions.value].sort((a, b) => 
      new Date(b.updated_at) - new Date(a.updated_at)
    )
  )
  
  // Actions
  async function fetchSessions(studentId = 'default_student') {
    loading.value = true
    try {
      const response = await sessionsApi.list(studentId)
      sessions.value = response.sessions
      return response.sessions
    } finally {
      loading.value = false
    }
  }
  
  async function createSession(title = '新会话') {
    const response = await sessionsApi.create({
      title,
      student_id: 'default_student'
    })
    sessions.value.unshift(response)
    currentSessionId.value = response.id
    return response
  }
  
  async function deleteSession(sessionId) {
    await sessionsApi.delete(sessionId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
    }
  }
  
  function setCurrentSession(sessionId) {
    currentSessionId.value = sessionId
  }
  
  return {
    sessions,
    currentSessionId,
    loading,
    currentSession,
    sortedSessions,
    fetchSessions,
    createSession,
    deleteSession,
    setCurrentSession
  }
})
```

- [ ] **Step 2: 创建聊天 Store**

```javascript
// frontend/src/stores/chat.js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi } from '../api/chat'

export const useChatStore = defineStore('chat', () => {
  // State
  const messages = ref([])
  const loading = ref(false)
  const streaming = ref(false)
  
  // Actions
  async function fetchHistory(sessionId) {
    const response = await chatApi.getHistory(sessionId)
    messages.value = response.messages
    return response.messages
  }
  
  async function sendMessage(sessionId, message, studentId = 'default_student') {
    loading.value = true
    
    // 先添加用户消息到列表
    messages.value.push({
      role: 'user',
      content: message,
      timestamp: new Date().toISOString()
    })
    
    try {
      const response = await chatApi.send({
        session_id: sessionId,
        message,
        student_id: studentId
      })
      
      messages.value.push(response.message)
      return response.message
    } finally {
      loading.value = false
    }
  }
  
  async function sendMessageStream(sessionId, message, onChunk) {
    streaming.value = true
    
    // 添加用户消息
    messages.value.push({
      role: 'user',
      content: message,
      timestamp: new Date().toISOString()
    })
    
    // 创建空的 AI 消息
    const aiMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    }
    messages.value.push(aiMessage)
    
    // 使用 SSE
    const params = new URLSearchParams({
      session_id: sessionId,
      message,
      student_id: 'default_student'
    })
    
    const eventSource = new EventSource(
      `/api/chat/send/stream?${params.toString()}`
    )
    
    return new Promise((resolve, reject) => {
      eventSource.onmessage = (event) => {
        if (event.data === '[DONE]') {
          eventSource.close()
          streaming.value = false
          resolve(aiMessage)
        } else {
          aiMessage.content = event.data
          if (onChunk) onChunk(event.data)
        }
      }
      
      eventSource.onerror = (error) => {
        eventSource.close()
        streaming.value = false
        reject(error)
      }
    })
  }
  
  function clearMessages() {
    messages.value = []
  }
  
  return {
    messages,
    loading,
    streaming,
    fetchHistory,
    sendMessage,
    sendMessageStream,
    clearMessages
  }
})
```

- [ ] **Step 3: 创建画像 Store**

```javascript
// frontend/src/stores/profile.js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { profileApi } from '../api/profile'

export const useProfileStore = defineStore('profile', () => {
  // State
  const summary = ref(null)
  const detail = ref(null)
  const loading = ref(false)
  
  // Actions
  async function fetchSummary(studentId = 'default_student') {
    loading.value = true
    try {
      const response = await profileApi.getSummary(studentId)
      summary.value = response
      return response
    } finally {
      loading.value = false
    }
  }
  
  async function fetchDetail(studentId = 'default_student') {
    loading.value = true
    try {
      const response = await profileApi.getDetail(studentId)
      detail.value = response
      return response
    } finally {
      loading.value = false
    }
  }
  
  async function refreshProfile(studentId = 'default_student') {
    await profileApi.aggregate(studentId)
    return fetchSummary(studentId)
  }
  
  return {
    summary,
    detail,
    loading,
    fetchSummary,
    fetchDetail,
    refreshProfile
  }
})
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/
git commit -m "feat: add Pinia stores for state management"
```

---

### Task 9: 聊天界面组件

**Files:**
- Create: `frontend/src/components/ChatSidebar.vue`
- Create: `frontend/src/components/ChatMessage.vue`
- Create: `frontend/src/components/ChatInput.vue`
- Create: `frontend/src/components/ProfileCard.vue`

- [ ] **Step 1: 创建侧边栏组件**

```vue
<!-- frontend/src/components/ChatSidebar.vue -->
<template>
  <aside class="w-72 bg-white border-r border-stone-200 flex flex-col h-full">
    <!-- 新建会话按钮 -->
    <div class="p-4">
      <el-button 
        type="primary" 
        class="w-full"
        size="large"
        @click="handleCreateSession"
      >
        <el-icon class="mr-2"><Plus /></el-icon>
        新建会话
      </el-button>
    </div>

    <!-- 会话列表 -->
    <el-scrollbar class="flex-1 px-3">
      <div class="text-xs text-stone-400 font-medium mb-2 px-2">
        最近会话
      </div>
      
      <div
        v-for="session in sessionStore.sortedSessions"
        :key="session.id"
        class="group rounded-lg p-3 mb-1 cursor-pointer transition-all"
        :class="{
          'bg-indigo-50 border-l-4 border-indigo-500': sessionStore.currentSessionId === session.id,
          'hover:bg-stone-50 border-l-4 border-transparent': sessionStore.currentSessionId !== session.id
        }"
        @click="selectSession(session.id)"
      >
        <div class="flex items-center justify-between">
          <span class="font-medium text-sm truncate flex-1"
            :class="sessionStore.currentSessionId === session.id ? 'text-indigo-900' : 'text-stone-700'"
          >
            {{ session.title }}
          </span>
          
          <el-button
            v-show="sessionStore.currentSessionId === session.id"
            type="danger"
            link
            size="small"
            @click.stop="handleDeleteSession(session.id)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
        
        <div class="text-xs text-stone-400 mt-1 flex items-center gap-2"
003e
          <span>💬 {{ session.message_count || 0 }} 条</span>
          <span>·</span>
          <span>{{ formatTime(session.updated_at) }}</span>
        </div>
      </div>
      
      <!-- 空状态 -->
      <el-empty
        v-if="sessionStore.sessions.length === 0"
        description="还没有会话"
        :image-size="80"
      />
    </el-scrollbar>

    <!-- 底部导航 -->
    <div class="p-4 border-t border-stone-200">
      <el-button 
        text 
        class="w-full justify-start"
        @click="$router.push('/profile')"
      >
        <el-icon class="mr-2"><DataAnalysis /></el-icon>
        学习画像
      </el-button>
    </div>
  </aside>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const sessionStore = useSessionStore()

onMounted(() => {
  sessionStore.fetchSessions()
})

function selectSession(sessionId) {
  sessionStore.setCurrentSession(sessionId)
  router.push(`/chat/${sessionId}`)
}

async function handleCreateSession() {
  const session = await sessionStore.createSession()
  ElMessage.success('创建成功')
  router.push(`/chat/${session.id}`)
}

async function handleDeleteSession(sessionId) {
  try {
    await ElMessageBox.confirm('确定删除这个会话吗？', '提示', {
      type: 'warning'
    })
    await sessionStore.deleteSession(sessionId)
    ElMessage.success('已删除')
    router.push('/chat')
  } catch {
    // 取消删除
  }
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now - date
  
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return `${Math.floor(diff / 86400000)}天前`
}
</script>
```

- [ ] **Step 2: 创建消息组件**

```vue
<!-- frontend/src/components/ChatMessage.vue -->
<template>
  <div 
    class="flex gap-4 mb-6"
    :class="{ 'flex-row-reverse': message.role === 'user' }"
  >
    <!-- 头像 -->
    <div 
      class="w-10 h-10 rounded-full flex items-center justify-center text-white font-medium flex-shrink-0"
      :class="message.role === 'user' 
        ? 'bg-gradient-to-br from-amber-400 to-orange-500'
        : 'bg-gradient-to-br from-indigo-500 to-violet-600'"
    >
      {{ message.role === 'user' ? '我' : '🤖' }}
    </div>

    <!-- 消息内容 -->
    <div 
      class="max-w-3xl p-4 rounded-2xl"
      :class="message.role === 'user'
        ? 'bg-indigo-600 text-white rounded-tr-sm'
        : 'bg-white border border-stone-200 rounded-tl-sm'"
    >
      <!-- 文本内容 -->
      <div 
        class="prose prose-stone max-w-none"
        :class="message.role === 'user' ? 'prose-invert' : ''"
        v-html="formattedContent"
      />
      
      <!-- 来源标注 -->
      <div 
        v-if="message.sources?.length > 0"
        class="mt-3 pt-3 border-t border-stone-200/50 text-xs flex items-center gap-2"
        :class="message.role === 'user' ? 'border-white/20' : ''"
      >
        <span class="opacity-60">📚</span>
        <span class="opacity-60">来源：{{ message.sources[0].reference }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

// 简单的 Markdown 格式化
const formattedContent = computed(() => {
  let content = props.message.content
  
  // 转义 HTML
  content = content.replace(/[<>]/g, m => m === '<' ? '&lt;' : '&gt;')
  
  // 代码块
  content = content.replace(/```([\s\S]*?)```/g, '<pre class="bg-stone-100 p-3 rounded-lg overflow-x-auto"><code>$1</code></pre>')
  
  // 行内代码
  content = content.replace(/`([^`]+)`/g, '<code class="bg-stone-100 px-1 rounded">$1</code>')
  
  // 粗体
  content = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  
  // 换行
  content = content.replace(/\n/g, '<br>')
  
  return content
})
</script>
```

- [ ] **Step 3: 创建输入组件**

```vue
<!-- frontend/src/components/ChatInput.vue -->
<template>
  <div class="border border-stone-200 rounded-2xl bg-white p-4 shadow-soft">
    <div class="flex items-end gap-3">
      <textarea
        v-model="inputText"
        rows="1"
        class="flex-1 bg-transparent border-none outline-none resize-none text-stone-700 placeholder-stone-400 min-h-[24px] max-h-[120px]"
        placeholder="输入问题，按 Enter 发送..."
        @keydown.enter.prevent="handleSend"
        @input="autoResize"
        ref="textareaRef"
      />
      
      <el-button
        type="primary"
        circle
        :disabled="!inputText.trim() || loading"
        :loading="loading"
        @click="handleSend"
        class="flex-shrink-0"
      >
        <!-- 箭头图标 -->
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
      </el-button>
    </div>
    
    <div class="text-center text-xs text-stone-400 mt-2">
      AI 助手基于课程教材回答，仅供参考
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['send'])

const inputText = ref('')
const textareaRef = ref(null)

function autoResize() {
  nextTick(() => {
    const textarea = textareaRef.value
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'
    }
  })
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.loading) return
  
  emit('send', text)
  inputText.value = ''
  
  // 重置高度
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })
}
</script>

<style scoped>
.shadow-soft {
  box-shadow: 0 1px 3px rgba(0,0,0,0.05),
              0 4px 12px rgba(0,0,0,0.04),
              0 8px 24px rgba(0,0,0,0.03);
}
</style>
```

- [ ] **Step 4: 创建画像卡片组件**

```vue
<!-- frontend/src/components/ProfileCard.vue -->
<template>
  <div class="bg-white rounded-2xl p-4 shadow-soft border border-stone-100">
    <div class="flex items-center justify-between mb-4">
      <h3 class="font-serif font-semibold text-stone-800 flex items-center gap-2">
        <span class="w-7 h-7 rounded-lg bg-indigo-100 flex items-center justify-center text-indigo-600">
          📊
        </span>
        学习快照
      </h3>
      
      <el-button 
        link 
        type="primary" 
        size="small"
        @click="$router.push('/profile')"
      >
        查看完整画像 →
      </el-button>
    </div>

    <!-- 加载中 -->
    <el-skeleton v-if="profileStore.loading" :rows="3" />

    <!-- 内容 -->
    <template v-else-if="profileStore.summary">
      <div class="space-y-4">
        <!-- 关注概念 -->
        <div>
          <div class="text-xs text-stone-500 mb-2 flex items-center gap-1">
            <span>🔥</span>
            <span>最近关注</span>
          </div>
          
          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="concept in profileStore.summary.recent_concepts.slice(0, 5)"
              :key="concept.concept_id"
              type="primary"
              effect="light"
              round
              size="small"
            >
              {{ concept.display_name }}
            </el-tag>
            
            <span 
              v-if="profileStore.summary.recent_concepts.length > 5"
              class="text-xs text-stone-400 self-center"
            >
              +{{ profileStore.summary.recent_concepts.length - 5 }}
            </span>
            
            <span 
              v-if="profileStore.summary.recent_concepts.length === 0"
              class="text-xs text-stone-400"
003e
              开始提问建立画像
            </span>
          </div>
        </div>

        <!-- 薄弱点 -->
        <div v-if="profileStore.summary.weak_spots.length > 0">
          <div class="text-xs text-stone-500 mb-2 flex items-center gap-1">
            <span>⚠️</span>
            <span>需要巩固</span>
          </div>
          
          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="spot in profileStore.summary.weak_spots.slice(0, 3)"
              :key="spot.concept_id"
              type="warning"
              effect="light"
              round
              size="small"
            >
              {{ spot.display_name }}
              <span class="ml-1 opacity-70">
                {{ Math.round(spot.confidence * 100) }}%
              </span>
            </el-tag>
          </div>
        </div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else class="text-center py-4">
      <p class="text-sm text-stone-400">暂无学习数据</p>
      <el-button 
        link 
        type="primary" 
        size="small"
        @click="profileStore.fetchSummary()"
      >
        刷新
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useProfileStore } from '../stores/profile'

const profileStore = useProfileStore()

onMounted(() => {
  profileStore.fetchSummary()
})
</script>

<style scoped>
.shadow-soft {
  box-shadow: 0 1px 3px rgba(0,0,0,0.05),
              0 4px 12px rgba(0,0,0,0.04),
              0 8px 24px rgba(0,0,0,0.03);
}
</style>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "feat: add chat UI components (sidebar, message, input, profile card)"
```

---

### Task 10: 主聊天视图

**Files:**
- Create: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/styles/main.scss`

- [ ] **Step 1: 创建全局样式**

```scss
// frontend/src/styles/main.scss
:root {
  --primary-indigo: #4f46e5;
  --primary-indigo-light: #e0e7ff;
  --accent-amber: #f59e0b;
  --warm-gray: #fafaf9;
  --paper: #fefdfb;
  --text-primary: #1c1917;
  --text-secondary: #78716c;
  --border-soft: #e7e5e4;
}

// 全局字体
body {
  font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
  background: linear-gradient(135deg, #fafaf9 0%, #f5f5f4 100%);
}

.font-serif {
  font-family: 'Noto Serif SC', serif;
}

// Element Plus 主题覆盖
:root {
  --el-color-primary: #4f46e5;
  --el-color-primary-light-3: #6366f1;
  --el-color-primary-light-5: #818cf8;
  --el-color-primary-light-7: #a5b4fc;
  --el-color-primary-light-8: #c7d2fe;
  --el-color-primary-light-9: #e0e7ff;
}

// 滚动条美化
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: #d6d3d1;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #a8a29e;
}

// 动画
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in {
  animation: fadeIn 0.3s ease;
}
```

- [ ] **Step 2: 创建主聊天视图**

```vue
<!-- frontend/src/views/ChatView.vue -->
<template>
  <div class="flex h-screen">
    <!-- 侧边栏 -->
    <ChatSidebar />

    <!-- 主内容区 -->
    <div class="flex-1 flex flex-col bg-gradient-to-br from-stone-50 to-stone-100">
      <!-- 顶部栏 -->
      <header class="h-16 bg-white border-b border-stone-200 flex items-center justify-between px-6">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-xl">
            🎓
          </div>
          <div>
            <h1 class="font-serif font-bold text-lg text-stone-900">智能课程助教</h1>
            <p class="text-xs text-stone-500">数据科学基础</p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <span class="text-sm text-stone-500">{{ currentSession?.title || '未选择会话' }}</span>
        </div>
      </header>

      <!-- 聊天区域 -->
      <div class="flex-1 overflow-hidden flex">
        <!-- 左侧聊天 -->
        <div class="flex-1 flex flex-col">
          <!-- 消息列表 -->
          <el-scrollbar ref="chatScrollbar" class="flex-1 px-6 py-4">
            <!-- 欢迎消息 -->
            <div v-if="chatStore.messages.length === 0" class="flex items-center justify-center h-full">
              <div class="text-center">
                <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-3xl mx-auto mb-4">
                  🤖
                </div>
                <h2 class="text-xl font-serif font-bold text-stone-800 mb-2">
                  你好！我是你的课程助教
                </h2>
                <p class="text-stone-500 max-w-md mx-auto">
                  我可以帮你理解课程概念、解答疑难问题、分析学习进度。
                  <br>在下方输入问题开始对话吧！
                </p>
              </div>
            </div>

            <!-- 消息气泡 -->
            <div v-else class="space-y-4">
              <ChatMessage
                v-for="(message, index) in chatStore.messages"
                :key="index"
                :message="message"
              />
              
              <!-- 正在输入提示 -->
              <div v-if="chatStore.loading || chatStore.streaming" class="flex gap-4">
                <div class="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white">
                  🤖
                </div>
                <div class="bg-white border border-stone-200 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1">
                  <span class="w-2 h-2 bg-stone-400 rounded-full animate-bounce"></span>
                  <span class="w-2 h-2 bg-stone-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></span>
                  <span class="w-2 h-2 bg-stone-400 rounded-full animate-bounce" style="animation-delay: 0.4s"></span>
                </div>
              </div>
            </div>
          </el-scrollbar>

          <!-- 输入区 -->
          <div class="px-6 py-4">
            <ChatInput
              :loading="chatStore.loading || chatStore.streaming"
              @send="handleSend"
            />
          </div>
        </div>

        <!-- 右侧画像卡片 -->
        <div class="w-80 p-6 hidden lg:block">
          <ProfileCard />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, computed, watch, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ChatSidebar from '../components/ChatSidebar.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import ProfileCard from '../components/ProfileCard.vue'

import { useSessionStore } from '../stores/session'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'

const route = useRoute()
const router = useRouter()
const chatScrollbar = ref(null)

const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()

const currentSession = computed(() => sessionStore.currentSession)

// 监听路由参数变化
watch(() => route.params.sessionId, (newId) => {
  if (newId) {
    loadSession(newId)
  } else if (sessionStore.sessions.length > 0) {
    // 默认选中第一个
    const first = sessionStore.sortedSessions[0]
    router.replace(`/chat/${first.id}`)
  }
}, { immediate: true })

async function loadSession(sessionId) {
  sessionStore.setCurrentSession(sessionId)
  await chatStore.fetchHistory(sessionId)
  scrollToBottom()
}

async function handleSend(message) {
  const sessionId = sessionStore.currentSessionId
  if (!sessionId) {
    // 没有会话时先创建一个
    const newSession = await sessionStore.createSession(message.slice(0, 20))
    await router.push(`/chat/${newSession.id}`)
    
    // 在新会话中发送消息
    await chatStore.sendMessage(newSession.id, message)
  } else {
    await chatStore.sendMessage(sessionId, message)
  }
  
  // 刷新画像
  await profileStore.fetchSummary()
  scrollToBottom()
}

function scrollToBottom() {
  setTimeout(() => {
    chatScrollbar.value?.scrollTo({
      top: 999999,
      behavior: 'smooth'
    })
  }, 100)
}

onMounted(() => {
  sessionStore.fetchSessions()
})
</script>
```

- [ ] **Step 3: 验证前端运行**

```bash
cd frontend
npm run dev
```

浏览器访问 `http://localhost:5173`，预期看到聊天界面，可以：
1. 创建新会话
2. 在输入框发送消息
3. 看到 AI 回复
4. 侧边栏显示会话列表

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: implement main chat view with profile card"
```

---

## 第三阶段：评估体系

### Task 11: 评估指标设计

**Files:**
- Create: `eval/metrics/retrieval.py`
- Create: `eval/metrics/answer.py`
- Create: `eval/data/qa_pairs.json`
- Create: `eval/scripts/run_benchmark.py`

- [ ] **Step 1: 创建检索质量评估指标**

```python
# eval/metrics/retrieval.py
"""
检索质量评估指标
"""
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class RetrievalMetrics:
    """检索评估结果"""
    recall@k: float  # 相关文档在 top-k 中的比例
    precision@k: float  # top-k 中相关文档的比例
    mrr: float  # 平均倒数排名
    ndcg@k: float  # 归一化折损累计增益


def calculate_recall_at_k(retrieved: List[str], relevant: List[str], k: int = 3) -> float:
    """
    计算 Recall@K
    
    Args:
        retrieved: 检索返回的文档ID列表
        relevant: 相关文档ID列表
        k: 评估前k个结果
    """
    retrieved_k = set(retrieved[:k])
    relevant_set = set(relevant)
    
    if not relevant_set:
        return 0.0
    
    return len(retrieved_k & relevant_set) / len(relevant_set)


def calculate_precision_at_k(retrieved: List[str], relevant: List[str], k: int = 3) -> float:
    """计算 Precision@K"""
    if k == 0:
        return 0.0
    
    retrieved_k = set(retrieved[:k])
    relevant_set = set(relevant)
    
    return len(retrieved_k & relevant_set) / k


def calculate_mrr(retrieved: List[str], relevant: List[str]) -> float:
    """
    计算 MRR (Mean Reciprocal Rank)
    第一个相关文档排名的倒数
    """
    relevant_set = set(relevant)
    
    for i, doc_id in enumerate(retrieved, 1):
        if doc_id in relevant_set:
            return 1.0 / i
    
    return 0.0


def calculate_ndcg_at_k(retrieved: List[str], relevance_scores: Dict[str, float], k: int = 3) -> float:
    """
    计算 NDCG@K (Normalized Discounted Cumulative Gain)
    
    Args:
        retrieved: 检索返回的文档ID列表
        relevance_scores: 文档ID到相关性分数的映射 (0-1)
        k: 评估前k个结果
    """
    def dcg(scores):
        """计算 DCG"""
        return sum((2 ** score - 1) / (i + 1) for i, score in enumerate(scores))
    
    # 实际 DCG
    actual_scores = [relevance_scores.get(doc_id, 0) for doc_id in retrieved[:k]]
    actual_dcg = dcg(actual_scores)
    
    # 理想 DCG
    ideal_scores = sorted(relevance_scores.values(), reverse=True)[:k]
    ideal_dcg = dcg(ideal_scores)
    
    if ideal_dcg == 0:
        return 0.0
    
    return actual_dcg / ideal_dcg


def evaluate_retrieval(
    query: str,
    retrieved_docs: List[Dict],
    ground_truth: Dict
) -> RetrievalMetrics:
    """
    评估单次检索质量
    
    Args:
        query: 查询问题
        retrieved_docs: 检索返回的文档列表 [{id, content, score}]
        ground_truth: 标准答案 {
            "relevant_doc_ids": [...],
            "relevance_scores": {doc_id: score}
        }
    """
    retrieved_ids = [doc["id"] for doc in retrieved_docs]
    relevant_ids = ground_truth.get("relevant_doc_ids", [])
    relevance_scores = ground_truth.get("relevance_scores", {})
    
    return RetrievalMetrics(
        recall@k=calculate_recall_at_k(retrieved_ids, relevant_ids),
        precision@k=calculate_precision_at_k(retrieved_ids, relevant_ids),
        mrr=calculate_mrr(retrieved_ids, relevant_ids),
        ndcg@k=calculate_ndcg_at_k(retrieved_ids, relevance_scores)
    )
```

- [ ] **Step 2: 创建回答质量评估指标**

```python
# eval/metrics/answer.py
"""
回答质量评估指标
"""
import re
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class AnswerMetrics:
    """回答评估结果"""
    relevance_score: float  # 相关性 (0-1)
    completeness_score: float  # 完整性 (0-1)
    correctness_score: float  # 正确性 (0-1)
    has_source: bool  # 是否包含来源
    keyword_coverage: float  # 关键词覆盖率
    avg_score: float  # 平均分


def calculate_keyword_coverage(answer: str, expected_keywords: List[str]) -> float:
    """
    计算关键词覆盖率
    
    Args:
        answer: AI 回答文本
        expected_keywords: 期望包含的关键词列表
    """
    if not expected_keywords:
        return 1.0
    
    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


def check_answer_relevance(answer: str, question: str, retrieved_context: str) -> float:
    """
    检查回答与问题的相关性
    基于关键词重叠和上下文引用
    """
    # 简单实现：检查问题关键词是否出现在回答中
    question_words = set(re.findall(r'\b\w{2,}\b', question.lower()))
    answer_words = set(re.findall(r'\b\w{2,}\b', answer.lower()))
    
    if not question_words:
        return 0.5
    
    overlap = len(question_words & answer_words)
    return min(1.0, overlap / len(question_words) * 1.5)


def check_completeness(answer: str, min_length: int = 50, ideal_length: int = 500) -> float:
    """
    检查回答完整性
    基于长度和结构完整性
    """
    length = len(answer)
    
    if length < min_length:
        return 0.3
    
    # 检查是否有结构化内容（列表、标题等）
    has_structure = bool(re.search(r'(\n[\-\*•]|\d+\.|\*\*|##?)', answer))
    
    length_score = min(1.0, length / ideal_length)
    structure_bonus = 0.2 if has_structure else 0
    
    return min(1.0, length_score + structure_bonus)


def check_source_citation(answer: str) -> bool:
    """检查是否包含来源引用"""
    source_patterns = [
        r'来源[：:]',
        r'参考[：:]',
        r'第\d+章',
        r'第\d+页',
        r'\[\d+\]',
    ]
    
    return any(re.search(p, answer) for p in source_patterns)


def evaluate_answer(
    question: str,
    answer: str,
    expected_keywords: List[str] = None,
    retrieved_context: str = ""
) -> AnswerMetrics:
    """
    评估回答质量
    
    Args:
        question: 原始问题
        answer: AI 生成的回答
        expected_keywords: 期望包含的关键词
        retrieved_context: 检索到的上下文（用于相关性判断）
    """
    expected_keywords = expected_keywords or []
    
    relevance = check_answer_relevance(answer, question, retrieved_context)
    completeness = check_completeness(answer)
    keyword_coverage = calculate_keyword_coverage(answer, expected_keywords)
    has_source = check_source_citation(answer)
    
    # 简单正确性判断：回答中是否包含"我不知道"、"无法回答"等逃避性语言
    evasive_patterns = [
        r'我不知道',
        r'无法回答',
        r'没有相关信息',
        r'对不起.*不能',
    ]
    is_evasive = any(re.search(p, answer) for p in evasive_patterns)
    correctness = 0.3 if is_evasive else 0.8  # 粗略估计
    
    # 平均分
    avg = (relevance + completeness + correctness + keyword_coverage) / 4
    
    return AnswerMetrics(
        relevance_score=relevance,
        completeness_score=completeness,
        correctness_score=correctness,
        has_source=has_source,
        keyword_coverage=keyword_coverage,
        avg_score=avg
    )
```

- [ ] **Step 3: 创建评测数据集**

```json
{
  "qa_pairs": [
    {
      "id": "eval_001",
      "question": "什么是支持向量机（SVM）？",
      "category": "概念理解",
      "expected_keywords": ["分类器", "超平面", "间隔", "最大化", "支持向量"],
      "ground_truth": {
        "relevant_doc_ids": ["doc_ch3_svm_intro", "doc_ch3_svm_theory"],
        "relevance_scores": {
          "doc_ch3_svm_intro": 1.0,
          "doc_ch3_svm_theory": 0.9,
          "doc_ch3_kernel": 0.5
        }
      },
      "evaluation_criteria": {
        "min_length": 100,
        "must_contain": ["超平面", "间隔"]
      }
    },
    {
      "id": "eval_002",
      "question": "梯度下降的学习率应该如何选择？",
      "category": "应用问题",
      "expected_keywords": ["学习率", "步长", "收敛", "过大", "过小", "自适应"],
      "ground_truth": {
        "relevant_doc_ids": ["doc_ch2_gradient_descent"],
        "relevance_scores": {
          "doc_ch2_gradient_descent": 1.0,
          "doc_ch2_optimization": 0.7
        }
      }
    },
    {
      "id": "eval_003",
      "question": "逻辑回归和线性回归有什么区别？",
      "category": "概念对比",
      "expected_keywords": ["分类", "回归", "离散", "连续", "sigmoid", "线性"],
      "ground_truth": {
        "relevant_doc_ids": ["doc_ch2_logistic_regression", "doc_ch2_linear_regression"],
        "relevance_scores": {
          "doc_ch2_logistic_regression": 1.0,
          "doc_ch2_linear_regression": 0.9
        }
      }
    },
    {
      "id": "eval_004",
      "question": "什么是过拟合？如何避免？",
      "category": "概念理解",
      "expected_keywords": ["过拟合", "泛化", "训练集", "测试集", "正则化", " dropout"],
      "ground_truth": {
        "relevant_doc_ids": ["doc_ch4_overfitting", "doc_ch4_regularization"],
        "relevance_scores": {
          "doc_ch4_overfitting": 1.0,
          "doc_ch4_regularization": 0.8
        }
      }
    },
    {
      "id": "eval_005",
      "question": "决策树的剪枝策略有哪些？",
      "category": "应用问题",
      "expected_keywords": ["预剪枝", "后剪枝", "剪枝", "深度", "叶子节点"],
      "ground_truth": {
        "relevant_doc_ids": ["doc_ch5_decision_tree"],
        "relevance_scores": {
          "doc_ch5_decision_tree": 1.0
        }
      }
    }
  ],
  "metadata": {
    "total_pairs": 5,
    "categories": ["概念理解", "应用问题", "概念对比"],
    "created_at": "2026-04-08",
    "version": "1.0"
  }
}
```

- [ ] **Step 4: 创建评测脚本**

```python
# eval/scripts/run_benchmark.py
"""
运行完整评测并生成报告
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval.metrics.retrieval import evaluate_retrieval, RetrievalMetrics
from eval.metrics.answer import evaluate_answer, AnswerMetrics
from core.rag import RAGService


class BenchmarkRunner:
    """评测运行器"""
    
    def __init__(self):
        self.rag_service = RAGService()
        self.results = []
    
    def load_qa_pairs(self, path: str = "eval/data/qa_pairs.json") -> List[Dict]:
        """加载评测数据集"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("qa_pairs", [])
    
    def evaluate_single(self, qa_pair: Dict) -> Dict:
        """评估单个问答对"""
        question = qa_pair["question"]
        print(f"\n评测: {question[:40]}...")
        
        # 1. 执行检索
        retrieved_docs = self.rag_service.retrieve(question, top_k=3)
        
        # 2. 生成回答
        answer = self.rag_service.answer_with_context(question, retrieved_docs)
        
        # 3. 评估检索质量
        retrieval_metrics = evaluate_retrieval(
            query=question,
            retrieved_docs=[{"id": d.metadata.get("id", str(i)), "content": d.page_content} 
                          for i, d in enumerate(retrieved_docs)],
            ground_truth=qa_pair.get("ground_truth", {})
        )
        
        # 4. 评估回答质量
        answer_metrics = evaluate_answer(
            question=question,
            answer=answer,
            expected_keywords=qa_pair.get("expected_keywords", []),
            retrieved_context="\n".join([d.page_content for d in retrieved_docs])
        )
        
        result = {
            "id": qa_pair["id"],
            "question": question,
            "category": qa_pair.get("category", "未知"),
            "answer": answer,
            "retrieval": {
                "recall@3": retrieval_metrics.recall@k,
                "precision@3": retrieval_metrics.precision@k,
                "mrr": retrieval_metrics.mrr,
                "ndcg@3": retrieval_metrics.ndcg@k
            },
            "answer_quality": {
                "relevance": answer_metrics.relevance_score,
                "completeness": answer_metrics.completeness_score,
                "correctness": answer_metrics.correctness_score,
                "has_source": answer_metrics.has_source,
                "keyword_coverage": answer_metrics.keyword_coverage,
                "avg_score": answer_metrics.avg_score
            }
        }
        
        print(f"  检索 Recall@3: {retrieval_metrics.recall@k:.2%}")
        print(f"  回答平均分: {answer_metrics.avg_score:.2%}")
        
        return result
    
    def run(self, output_path: str = None) -> Dict:
        """运行完整评测"""
        qa_pairs = self.load_qa_pairs()
        print(f"开始评测，共 {len(qa_pairs)} 条问答对...")
        print("=" * 60)
        
        self.results = []
        for qa in qa_pairs:
            try:
                result = self.evaluate_single(qa)
                self.results.append(result)
            except Exception as e:
                print(f"  ❌ 评测失败: {e}")
                self.results.append({
                    "id": qa["id"],
                    "error": str(e)
                })
        
        # 生成汇总报告
        report = self.generate_report()
        
        # 保存报告
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\n报告已保存: {output_path}")
        
        return report
    
    def generate_report(self) -> Dict:
        """生成评测报告"""
        valid_results = [r for r in self.results if "error" not in r]
        
        # 计算平均指标
        avg_retrieval = {
            "recall@3": sum(r["retrieval"]["recall@3"] for r in valid_results) / len(valid_results),
            "precision@3": sum(r["retrieval"]["precision@3"] for r in valid_results) / len(valid_results),
            "mrr": sum(r["retrieval"]["mrr"] for r in valid_results) / len(valid_results),
            "ndcg@3": sum(r["retrieval"]["ndcg@3"] for r in valid_results) / len(valid_results)
        }
        
        avg_answer = {
            "relevance": sum(r["answer_quality"]["relevance"] for r in valid_results) / len(valid_results),
            "completeness": sum(r["answer_quality"]["completeness"] for r in valid_results) / len(valid_results),
            "correctness": sum(r["answer_quality"]["correctness"] for r in valid_results) / len(valid_results),
            "has_source_rate": sum(r["answer_quality"]["has_source"] for r in valid_results) / len(valid_results),
            "keyword_coverage": sum(r["answer_quality"]["keyword_coverage"] for r in valid_results) / len(valid_results),
            "avg_score": sum(r["answer_quality"]["avg_score"] for r in valid_results) / len(valid_results)
        }
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_evaluated": len(self.results),
                "successful": len(valid_results),
                "failed": len(self.results) - len(valid_results)
            },
            "retrieval_metrics": avg_retrieval,
            "answer_metrics": avg_answer,
            "overall_score": (avg_retrieval["recall@3"] + avg_answer["avg_score"]) / 2,
            "detailed_results": self.results
        }
        
        # 打印报告
        print("\n" + "=" * 60)
        print("评测报告")
        print("=" * 60)
        print(f"总样本数: {report['summary']['total_evaluated']}")
        print(f"成功: {report['summary']['successful']} | 失败: {report['summary']['failed']}")
        print("\n【检索质量】")
        print(f"  Recall@3:    {avg_retrieval['recall@3']:.2%}")
        print(f"  Precision@3: {avg_retrieval['precision@3']:.2%}")
        print(f"  MRR:         {avg_retrieval['mrr']:.3f}")
        print(f"  NDCG@3:      {avg_retrieval['ndcg@3']:.3f}")
        print("\n【回答质量】")
        print(f"  相关性:      {avg_answer['relevance']:.2%}")
        print(f"  完整性:      {avg_answer['completeness']:.2%}")
        print(f"  正确性:      {avg_answer['correctness']:.2%}")
        print(f"  来源引用率:  {avg_answer['has_source_rate']:.2%}")
        print(f"  关键词覆盖:  {avg_answer['keyword_coverage']:.2%}")
        print(f"  综合得分:    {avg_answer['avg_score']:.2%}")
        print("\n【总体评分】")
        print(f"  总分:        {report['overall_score']:.2%}")
        
        return report


if __name__ == "__main__":
    runner = BenchmarkRunner()
    report = runner.run("eval/reports/benchmark_report.json")
```

- [ ] **Step 5: 运行评测验证**

```bash
cd F:\Projects\RAG_System
python eval/scripts/run_benchmark.py
```

预期输出：评测报告，包含检索质量和回答质量的各项指标

- [ ] **Step 6: Commit**

```bash
git add eval/
git commit -m "feat: implement evaluation system with retrieval and answer quality metrics"
```

---

## 第四阶段：部署配置

### Task 12: Docker 部署

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: 创建后端 Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY app/ ./app/
COPY tests/ ./tests/

# 复制核心模块（从项目根目录）
COPY ../core/ ./core/
COPY ../skills/ ./skills/
COPY ../utils/ ./utils/
COPY ../kb_builder/ ./kb_builder/
COPY ../eval/ ./eval/
COPY ../data/ ./data/
COPY ../chroma_db/ ./chroma_db/
COPY ../chat_history/ ./chat_history/

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 创建前端 Dockerfile**

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

# 安装依赖
COPY package*.json ./
RUN npm ci

# 复制源码
COPY . .

# 构建
RUN npm run build

# 使用 nginx 提供服务
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 3: 创建 nginx 配置**

```nginx
# frontend/nginx.conf
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # 前端路由支持
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理
    location /api {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # 静态文件缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

- [ ] **Step 4: 创建 docker-compose.yml**

```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: rag-backend
    ports:
      - "8000:8000"
    volumes:
      - ./chroma_db:/app/chroma_db
      - ./chat_history:/app/chat_history
      - ./data:/app/data
    environment:
      - PYTHONUNBUFFERED=1
    networks:
      - rag-network

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: rag-frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    networks:
      - rag-network

networks:
  rag-network:
    driver: bridge
```

- [ ] **Step 5: 创建 .dockerignore**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/

# Node
node_modules/
npm-debug.log*

# IDE
.vscode/
.idea/
*.swp
*.swo

# Git
.git/
.gitignore

# 其他
*.md
.DS_Store
```

- [ ] **Step 6: 测试 Docker 构建**

```bash
# 构建并启动
docker-compose up --build

# 验证
curl http://localhost/health
curl http://localhost/api/health
```

- [ ] **Step 7: Commit**

```bash
git add Dockerfile* docker-compose.yml .dockerignore
git commit -m "feat: add Docker deployment configuration"
```

---

## 里程碑总结

| 阶段 | 任务 | 交付物 | 验收标准 |
|------|------|--------|----------|
| **Phase 1** | 后端 API 开发 | FastAPI 服务 | API 测试全部通过 |
| **Phase 2** | 前端开发 | Vue3 应用 | 界面可用，功能完整 |
| **Phase 3** | 评估体系 | 评测脚本 | 可运行并得到指标报告 |
| **Phase 4** | 部署配置 | Docker Compose | 一键启动完整服务 |

**总工作量估计**: 4-6 周（1人全职）

---

## 下一步行动建议

**计划已完成并保存到 `docs/superpowers/plans/2026-04-08-rag-production-plan.md`**

两种执行方式可选：

1. **Subagent-Driven（推荐）** - 每个 Task 由独立子代理执行，我在关键节点审查
2. **Inline Execution** - 在当前会话中顺序执行

你希望如何开始？
