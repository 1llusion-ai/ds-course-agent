"""
桥接现有 core/ 模块与 FastAPI
"""
import sys
import os
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

import traceback
from pathlib import Path
from dotenv import load_dotenv

# 确定项目根目录（处理worktree情况）
_current_file = Path(__file__).resolve()
PROJECT_ROOT = _current_file.parents[3]

_main_project_root = PROJECT_ROOT
if (_main_project_root / ".worktrees").exists() or not (_main_project_root / ".env").exists():
    for parent in _main_project_root.parents:
        if (parent / ".env").exists() and (parent / "core").exists():
            _main_project_root = parent
            break

_main_env_path = _main_project_root / ".env"
if _main_env_path.exists():
    load_dotenv(_main_env_path, override=True)
    print(f"[CoreBridge] Loaded .env from {_main_env_path}")
else:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    print(f"[CoreBridge] Loaded .env from {PROJECT_ROOT / '.env'}")

sys.path.insert(0, str(_main_project_root))
if str(PROJECT_ROOT) != str(_main_project_root):
    sys.path.insert(0, str(PROJECT_ROOT))

PROJECT_ROOT = _main_project_root

_agent_service = None
_memory_core = None


def get_memory_core():
    global _memory_core
    if _memory_core is None:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.memory_core import get_memory_core as _get_core
        _memory_core = _get_core()
    return _memory_core


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.agent import get_agent_service as _get_service
        _agent_service = _get_service()
    return _agent_service


def chat_with_history(message: str, session_id: str, student_id: str) -> dict:
    from core.tools import begin_retrieval_trace, end_retrieval_trace

    token = begin_retrieval_trace()

    try:
        service = get_agent_service()
        content = service.chat_with_history(
            user_input=message,
            session_id=session_id,
            student_id=student_id
        )
    except Exception as e:
        print(f"[Agent Error] {e}")
        traceback.print_exc()
        content = f"关于「{message}」的问题，我需要查阅课程资料后才能回答。\n\n（Agent调用出错：{str(e)[:100]}）"
    finally:
        trace = end_retrieval_trace(token)

    return {
        "content": content,
        "used_retrieval": trace.used_retrieval,
        "sources": trace.sources,
    }


def stream_chat_with_history(message: str, session_id: str, student_id: str):
    from core.tools import begin_retrieval_trace, end_retrieval_trace

    token = begin_retrieval_trace()
    final_content = ""

    try:
        service = get_agent_service()
        for event in service.stream_chat_with_history(
            user_input=message,
            session_id=session_id,
            student_id=student_id,
        ):
            event_type = event.get("type")
            if event_type == "delta":
                yield event
            elif event_type == "done":
                final_content = event.get("content", "")
    except Exception as e:
        print(f"[Agent Stream Error] {e}")
        traceback.print_exc()
        final_content = (
            f"关于“{message}”的问题，我需要查阅课程资料后才能回答。\n\n"
            f"（流式调用出错：{str(e)[:100]}）"
        )
    finally:
        trace = end_retrieval_trace(token)

    yield {
        "type": "final",
        "content": final_content,
        "used_retrieval": trace.used_retrieval,
        "sources": trace.sources,
    }
