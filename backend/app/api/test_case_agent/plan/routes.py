"""POST /api/test-case-agent/plan 及子路径。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import app.api.test_case_agent.common as common
from app.schemas.agent_io import (
    McpDocumentToolRawEntry,
    ModulePlan,
    PlanModulesOnlyRequest,
    PlanModulesOnlyResponse,
    PlanRequirementSourceRequest,
    PlanRequirementSourceResponse,
    PlanSkeletonRequest,
    PlanSkeletonResponse,
)
from app.schemas.mindmap import MindMapNode
from app.services.mcp_loader import load_mcp_servers_config, should_use_mcp
from app.services.test_case_llm import (
    fetch_plan_mcp_document_brief,
    plan_modules_without_skeleton,
    plan_skeleton_mind_map_only,
    plan_test_case_modules,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def post_plan(request: Request) -> Any:
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /plan JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    requirement = str(body.get("requirement") or "").strip()
    if not requirement:
        logger.warning("POST /plan 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if common._openai_key_missing():
        logger.warning("POST /plan 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    logger.info(
        "POST /plan 阶段=模块规划 开始 requirement_chars=%s mcp_rule_hit=%s mcp_servers_configured=%s",
        len(requirement),
        should_use_mcp(requirement),
        bool(load_mcp_servers_config()),
    )
    try:
        result = await plan_test_case_modules(requirement)
        mods = result.get("modules") if isinstance(result, dict) else None
        n = len(mods) if isinstance(mods, list) else 0
        logger.info(
            "POST /plan 阶段=模块规划 成功 modules=%s summary_chars=%s",
            n,
            len(str(result.get("summary") or "")),
        )
        return result
    except Exception as e:
        logger.exception("POST /plan 失败")
        return common._handle_unknown(e)


@router.post("/requirement-source")
async def post_plan_requirement_source(payload: PlanRequirementSourceRequest) -> Any:
    """MCP Phase1-only：外链/知识库取证，返回 ``mcpDocumentBrief``。"""
    requirement = str(payload.requirement or "").strip()
    if not requirement:
        logger.warning("POST /plan/requirement-source 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if common._openai_key_missing():
        logger.warning("POST /plan/requirement-source 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    logger.info(
        "POST /plan/requirement-source 开始 requirement_chars=%s mcp_rule_hit=%s mcp_servers_configured=%s",
        len(requirement),
        should_use_mcp(requirement),
        bool(load_mcp_servers_config()),
    )
    try:
        data = await fetch_plan_mcp_document_brief(requirement)
        brief = str(data.get("mcpDocumentBrief") or "")
        raw = data.get("mcpDocumentToolRaw")
        tool_entries: list[McpDocumentToolRawEntry] | None = None
        if raw is not None:
            tool_entries = [McpDocumentToolRawEntry.model_validate(x) for x in raw]
        logger.info(
            "POST /plan/requirement-source 成功 mcpDocumentBrief_chars=%s mcpDocumentToolRaw_count=%s",
            len(brief),
            len(tool_entries or []),
        )
        return PlanRequirementSourceResponse(
            mcp_document_brief=brief,
            mcp_document_tool_raw=tool_entries,
        ).model_dump(mode="python", by_alias=True)
    except Exception as e:
        logger.exception("POST /plan/requirement-source 失败")
        return common._handle_unknown(e)


@router.post("/modules")
async def post_plan_modules(payload: PlanModulesOnlyRequest) -> Any:
    """结构化生成一级模块 ``summary`` + ``modules``；可附带 ``mcpDocumentBrief`` 跳过 MCP Phase1。"""
    requirement = str(payload.requirement or "").strip()
    if not requirement:
        logger.warning("POST /plan/modules 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if common._openai_key_missing():
        logger.warning("POST /plan/modules 拒绝: 未配置 OPENAI_API_KEY")
        return common._err_500_key()
    logger.info(
        "POST /plan/modules 阶段=模块结构化 开始 requirement_chars=%s has_mcpBrief=%s",
        len(requirement),
        bool(payload.mcp_document_brief and str(payload.mcp_document_brief).strip()),
    )
    try:
        result = await plan_modules_without_skeleton(
            requirement, mcp_document_brief=payload.mcp_document_brief
        )
        mods_norm = result.get("modules") if isinstance(result, dict) else None
        n = len(mods_norm) if isinstance(mods_norm, list) else 0
        logger.info("POST /plan/modules 成功 modules=%s", n)
        modules_pv: list[ModulePlan] = []
        if isinstance(mods_norm, list):
            for x in mods_norm:
                if isinstance(x, dict):
                    modules_pv.append(ModulePlan.model_validate(x))
        return PlanModulesOnlyResponse(
            summary=str(result.get("summary") or ""),
            modules=modules_pv,
        ).model_dump(mode="python", by_alias=True)
    except Exception as e:
        logger.exception("POST /plan/modules 失败")
        return common._handle_unknown(e)


@router.post("/skeleton")
async def post_plan_skeleton(payload: PlanSkeletonRequest) -> Any:
    """由模块列表确定性生成骨架 ``mindMap``（无 LLM）。"""
    raw = [m.model_dump(by_alias=True) for m in payload.modules]
    logger.info("POST /plan/skeleton 开始 modules_input=%s", len(raw))
    try:
        out = plan_skeleton_mind_map_only(raw)
        validated = MindMapNode.model_validate(out["mindMap"])
        return PlanSkeletonResponse(
            mind_map=validated,
        ).model_dump(mode="python", by_alias=True)
    except ValidationError:
        logger.warning("POST /plan/skeleton 脑图结构校验失败")
        return JSONResponse(status_code=400, content={"error": "mindMap 拼装结果不符合约定结构"})
    except Exception as e:
        logger.exception("POST /plan/skeleton 失败")
        return common._handle_unknown(e)
