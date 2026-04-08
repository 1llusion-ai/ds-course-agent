"""桥接现有 core/ 模块与 FastAPI"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 预加载依赖模块，避免 core/__init__.py 被触发
def _preload_dependencies():
    """预加载 core 模块依赖，避免 __init__.py 的自动导入链"""
    import importlib.util

    # 加载 profile_models
    if "core.profile_models" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "core.profile_models", PROJECT_ROOT / "core" / "profile_models.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["core.profile_models"] = module
        spec.loader.exec_module(module)

    # 加载 events
    if "core.events" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "core.events", PROJECT_ROOT / "core" / "events.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["core.events"] = module
        spec.loader.exec_module(module)

    # 创建一个空的 core 模块占位符
    if "core" not in sys.modules:
        import types
        core_module = types.ModuleType("core")
        sys.modules["core"] = core_module

# 预加载依赖
_preload_dependencies()

_agent_service = None
_memory_core = None


def get_memory_core():
    global _memory_core
    if _memory_core is None:
        # 现在可以安全导入 memory_core
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "core.memory_core", PROJECT_ROOT / "core" / "memory_core.py"
        )
        memory_core_module = importlib.util.module_from_spec(spec)
        sys.modules["core.memory_core"] = memory_core_module
        spec.loader.exec_module(memory_core_module)
        _memory_core = memory_core_module.get_memory_core()
    return _memory_core


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        from core.agent import get_agent_service as _get_service
        _agent_service = _get_service()
    return _agent_service


def chat_with_history(message: str, session_id: str, student_id: str) -> str:
    service = get_agent_service()
    return service.chat_with_history(
        user_input=message,
        session_id=session_id,
        student_id=student_id
    )
