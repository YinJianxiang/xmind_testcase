"""
测试用例 Agent REST：`/api/test-case-agent/*`。

目录按功能拆分（类似 Next App Router：``plan`` / ``module`` / ``chat`` / ``export-xmind``），
Python 包名不能用连字符，``export-xmind`` 对应包 ``export_xmind``。

根路径 ``POST /api/test-case-agent``（legacy）写在本文件末尾：FastAPI 不允许子路由以空路径 ``include_router``。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.test_case_agent.chat.routes import router as chat_router
from app.api.test_case_agent.export_xmind.routes import router as export_xmind_router
from app.api.test_case_agent.module.routes import router as module_router
from app.api.test_case_agent.plan.routes import router as plan_router
import app.api.test_case_agent.common as common
from app.services.mcp_loader import load_mcp_servers_config, should_use_mcp
from app.services.test_case_llm import generate_test_cases

# 供单测 patch：``patch("app.api.test_case_agent.common._openai_key_missing")``
from app.api.test_case_agent.common import (
    _err_500_key,
    _handle_unknown,
    _mcp_rule_hit_from_chat_messages,
    _openai_key_missing,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["test-case-agent"])
router.include_router(plan_router, prefix="/plan")
router.include_router(module_router, prefix="/module")
router.include_router(chat_router, prefix="/chat")
router.include_router(export_xmind_router, prefix="/export-xmind")


@router.get("/mcp-diagnostics")
def get_mcp_diagnostics() -> dict[str, Any]:
    """开发辅助：当前工作目录 ``mcp.json`` 与 ``should_use_mcp`` 命中示例（不发起真实 MCP 连接）。"""
    path = Path.cwd() / "mcp.json"
    exists = path.is_file()
    cfg = load_mcp_servers_config()
    servers = list(cfg.keys()) if exists else []
    return {
        "mcp_json_exists": exists,
        "servers": servers,
        "connect_probe": None,
        "should_use_mcp_examples": {
            "plain_text": should_use_mcp("hello world only"),
            "https_url": should_use_mcp("see https://x.feishu.cn/wiki/abc"),
        },
    }


@router.post("")
@router.post("/")
async def post_generate_legacy(request: Request) -> Any:
    """`POST /api/test-case-agent`（根），对齐 `route.ts`。"""
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /api/test-case-agent (legacy) JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    requirement = str(body.get("requirement") or "").strip()
    if not requirement:
        logger.warning("POST /api/test-case-agent 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if common._openai_key_missing():
        logger.warning("POST /api/test-case-agent 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    logger.info(
        "POST /api/test-case-agent (legacy) 阶段=全文用例生成 开始 requirement_chars=%s "
        "mcp_rule_hit=%s mcp_servers_configured=%s",
        len(requirement),
        should_use_mcp(requirement),
        bool(load_mcp_servers_config()),
    )
    try:
        result = await generate_test_cases(requirement)
        cases = result.get("cases") if isinstance(result, dict) else None
        nc = len(cases) if isinstance(cases, list) else 0
        logger.info(
            "POST /api/test-case-agent (legacy) 阶段=全文用例生成 成功 cases=%s summary_chars=%s",
            nc,
            len(str(result.get("summary") or "")),
        )
        return result
    except Exception as e:
        logger.exception("POST /api/test-case-agent (legacy) 失败")
        return common._handle_unknown(e)


__all__ = [
    "_err_500_key",
    "_handle_unknown",
    "_mcp_rule_hit_from_chat_messages",
    "_openai_key_missing",
    "router",
]
