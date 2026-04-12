"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import chat, profile, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[START] RAG Tutor Backend Service starting...")
    yield
    print("[STOP] RAG Tutor Backend Service stopped")


app = FastAPI(
    title="RAG 课程助教 API",
    description="智能课程助教系统后端 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])


@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "rag-tutor-backend"}


__all__ = ["app"]
