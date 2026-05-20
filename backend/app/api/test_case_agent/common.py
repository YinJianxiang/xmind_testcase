"""API 层共享：鉴权、错误响应、MCP 命中辅助。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse

from app.config import settings
from app.services.mcp_loader import should_use_mcp

logger = logging.getLogger(__name__)


def _mcp_rule_hit_from_chat_messages(messages_dicts: list[dict[str, Any]]) -> bool:
    """根据对话里用户消息的文本判断是否命中 MCP 触发规则（与完整 prompt 可能略有出入）。"""
    blob = "\n".join(str(m.get("content") or "") for m in messages_dicts if m.get("role") == "user")
    return should_use_mcp(blob)


def _openai_key_missing() -> bool:
    k = settings.openai_api_key
    return not k or not str(k).strip()


def _err_500_key() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "请先配置 OPENAI_API_KEY"},
    )


def _handle_unknown(exc: BaseException) -> JSONResponse:
    msg = str(exc) if isinstance(exc, Exception) else "未知错误"
    return JSONResponse(status_code=500, content={"error": msg})
