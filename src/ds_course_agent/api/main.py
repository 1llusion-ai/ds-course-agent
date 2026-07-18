"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import ds_course_agent.shared.config as config
from ds_course_agent.shared.logging_config import setup_logging

# 在应用启动时初始化日志（必须在导入其他业务模块之前）
setup_logging(level=config.LOG_LEVEL)

from .auth import models as auth_models
from .auth.router import router as auth_router
from .routers import chat, profile, sessions

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RAG Tutor Backend Service starting...")
    auth_models.init_db()
    yield
    logger.info("RAG Tutor Backend Service stopped")


app = FastAPI(
    title="RAG 课程助教 API",
    description="智能课程助教系统后端 API",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_origins = [
    origin.strip() for origin in str(getattr(config, "CORS_ALLOW_ORIGINS", "") or "").split(",") if origin.strip()
]
if not _cors_origins:
    _cors_origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
    ]

auth_models.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])


@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "rag-tutor-backend"}


__all__ = ["app"]
