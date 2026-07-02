"""
集中式日志配置模块
在应用启动时调用 setup_logging() 初始化，各模块通过 get_logger(name) 获取 logger。

日志级别可通过环境变量 LOG_LEVEL 控制（DEBUG / INFO / WARNING / ERROR），默认 INFO。
"""
import logging
import os
import sys
from pathlib import Path

from ds_course_agent.shared.paths import PROJECT_ROOT


_initialized = False


def setup_logging(level: str | None = None) -> None:
    """
    初始化全局日志配置。重复调用安全（仅首次生效）。

    Args:
        level: 日志级别字符串，None 时从环境变量 LOG_LEVEL 读取，默认 INFO。
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()

    log_level = getattr(logging, level, logging.INFO)

    # 日志格式
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 文件输出（可选）
    handlers: list[logging.Handler] = [console_handler]
    log_dir = PROJECT_ROOT / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "app.log", encoding="utf-8", delay=True
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError:
        # 文件不可写时静默降级，只用控制台
        pass

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    # 降低第三方库的日志噪音
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "chromadb", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 logger，通常传 __name__。"""
    return logging.getLogger(name)
