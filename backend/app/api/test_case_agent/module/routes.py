"""POST /api/test-case-agent/module。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import app.api.test_case_agent.common as common
from app.schemas.agent_io import ModuleRequest
from app.services.mcp_loader import load_mcp_servers_config, should_use_mcp
from app.services.test_case_llm import generate_module_test_cases

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def post_module(request: Request) -> Any:
    if common._openai_key_missing():
        logger.warning("POST /module 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /module JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})
    try:
        req = ModuleRequest.model_validate(body)
    except ValidationError:
        logger.warning("POST /module 参数校验失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    module_d = req.module.model_dump(by_alias=True)
    modules_d = [m.model_dump(by_alias=True) for m in req.modules]
    title = str(module_d.get("title") or "")
    logger.info(
        "POST /module 阶段=单模块用例生成 开始 module_title=%s modules_total=%s requirement_chars=%s "
        "mcp_rule_hit=%s mcp_servers_configured=%s mcp_prefetch=%s",
        title[:120],
        len(modules_d),
        len(req.requirement or ""),
        should_use_mcp(req.requirement or ""),
        bool(load_mcp_servers_config()),
        bool((req.mcp_document_brief or "").strip()),
    )
    try:
        result = await generate_module_test_cases(
            req.requirement,
            module_d,
            modules_d,
            mcp_document_brief=req.mcp_document_brief,
        )
        cases = result.get("cases") if isinstance(result, dict) else None
        nc = len(cases) if isinstance(cases, list) else 0
        logger.info(
            "POST /module 阶段=单模块用例生成 成功 module_title=%s cases=%s summary_chars=%s",
            title[:120],
            nc,
            len(str(result.get("summary") or "")),
        )
        return result
    except ValueError as e:
        logger.warning("POST /module 业务错误: %s", e)
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.exception("POST /module 失败")
        return common._handle_unknown(e)
