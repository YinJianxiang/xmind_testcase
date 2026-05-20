"""POST /api/test-case-agent/chat。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import app.api.test_case_agent.common as common
from app.schemas.agent_io import ChatRequest
from app.services.mcp_loader import load_mcp_servers_config
from app.services.test_case_llm import chat_and_update_mind_map

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def post_chat(request: Request) -> Any:
    if common._openai_key_missing():
        logger.warning("POST /chat 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /chat JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})
    try:
        req = ChatRequest.model_validate(body)
    except ValidationError:
        logger.warning("POST /chat 参数校验失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    messages_d = [m.model_dump() for m in req.messages]
    mind_d = req.current_mind_map.model_dump(mode="python")
    logger.info(
        "POST /chat 阶段=对话改脑图 开始 messages=%s mcp_rule_hit=%s mcp_servers_configured=%s",
        len(messages_d),
        common._mcp_rule_hit_from_chat_messages(messages_d),
        bool(load_mcp_servers_config()),
    )
    try:
        result = await chat_and_update_mind_map(messages_d, mind_d)
        logger.info(
            "POST /chat 阶段=对话改脑图 成功 reply_chars=%s",
            len(str(result.get("assistantReply") or "")),
        )
        return result
    except Exception as e:
        logger.exception("POST /chat 失败")
        return common._handle_unknown(e)
