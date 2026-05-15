"""应用启动时统一日志级别（业务 ``app.*`` 与可选第三方库）。"""

from __future__ import annotations

import logging
import sys

from app.config import settings

# 请求「每步」时常看的命名空间；DEBUG 下会非常冗长
_FRAMEWORK_DEBUG_LOGGERS = (
    "langchain",
    "langchain.agents",
    "langgraph",
    "langchain_core",
    "langchain_openai",
    "langchain_mcp_adapters",
    "openai",
    "httpx",
    "httpcore",
)


def configure_logging() -> None:
    raw = (settings.log_level or "INFO").strip().upper()
    level = getattr(logging, raw, logging.INFO)

    root = logging.getLogger()
    # Uvicorn 默认只为 ``uvicorn*`` 配 handler，不为 root；``app.*`` 会冒泡到 root 却无输出。
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("app").setLevel(level)

    # INFO：第三方默认 WARNING，控制台安静；DEBUG：打开链路细节
    fw_level = logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    for name in _FRAMEWORK_DEBUG_LOGGERS:
        logging.getLogger(name).setLevel(fw_level)
