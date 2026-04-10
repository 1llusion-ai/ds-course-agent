"""
Backend 状态持久化
将会话列表和聊天历史持久化到 chat_history/backend_state.json
避免 Backend 重启后数据丢失
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(_PROJECT_ROOT))
import utils.config as config

STATE_FILE = Path(config.CHAT_HISTORY_DIR) / "backend_state.json"

_sessions: Dict[str, dict] = {}
_chat_history: Dict[str, List[dict]] = {}


def _load():
    global _sessions, _chat_history
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _sessions = data.get("sessions", {})
            _chat_history = data.get("chat_history", {})
        except Exception:
            _sessions = {}
            _chat_history = {}
    else:
        _sessions = {}
        _chat_history = {}


def _save():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # datetime 对象无法直接序列化 -> 转成 ISO 字符串
    STATE_FILE.write_text(
        json.dumps(
            {"sessions": _sessions, "chat_history": _chat_history},
            ensure_ascii=False,
            default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o),
        ),
        encoding="utf-8",
    )


_load()
