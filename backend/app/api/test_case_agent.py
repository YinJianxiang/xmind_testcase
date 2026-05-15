"""
§7 REST：`/api/test-case-agent/*`。
错误信息与 HTTP 状态码对齐 Next `route.ts` / 附录 A。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.config import settings
from app.schemas.agent_io import (
    ChatRequest,
    ExportXmindRequest,
    McpDocumentToolRawEntry,
    ModulePlan,
    ModuleRequest,
    PlanModulesOnlyRequest,
    PlanModulesOnlyResponse,
    PlanRequirementSourceRequest,
    PlanRequirementSourceResponse,
    PlanSkeletonRequest,
    PlanSkeletonResponse,
)
from app.schemas.mindmap import MindMapNode
from app.services.test_case_llm import (
    chat_and_update_mind_map,
    fetch_plan_mcp_document_brief,
    generate_module_test_cases,
    generate_test_cases,
    plan_skeleton_mind_map_only,
    plan_modules_without_skeleton,
    plan_test_case_modules,
)
from app.services.xmind_export import build_xmind_zip, content_disposition_filename
from app.services.mcp_loader import load_mcp_servers_config, should_use_mcp

router = APIRouter(tags=["test-case-agent"])
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


@router.post("/plan")
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
    if _openai_key_missing():
        logger.warning("POST /plan 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        return _handle_unknown(e)
from app.schemas.mindmap import MindMapNode


@router.post("/plan/requirement-source")
async def post_plan_requirement_source(payload: PlanRequirementSourceRequest) -> Any:
    """MCP Phase1-only：外链/知识库取证，返回 ``mcpDocumentBrief``。"""
    requirement = str(payload.requirement or "").strip()
    if not requirement:
        logger.warning("POST /plan/requirement-source 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if _openai_key_missing():
        logger.warning("POST /plan/requirement-source 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        return _handle_unknown(e)


@router.post("/plan/modules")
async def post_plan_modules(payload: PlanModulesOnlyRequest) -> Any:
    """结构化生成一级模块 ``summary`` + ``modules``；可附带 ``mcpDocumentBrief`` 跳过 MCP Phase1。"""
    requirement = str(payload.requirement or "").strip()
    if not requirement:
        logger.warning("POST /plan/modules 拒绝: requirement 为空")
        return JSONResponse(status_code=400, content={"error": "requirement 不能为空"})
    if _openai_key_missing():
        logger.warning("POST /plan/modules 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        return _handle_unknown(e)


@router.post("/plan/skeleton")
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
        return _handle_unknown(e)


@router.post("/module")
async def post_module(request: Request) -> Any:
    if _openai_key_missing():
        logger.warning("POST /module 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        return _handle_unknown(e)


@router.post("/chat")
async def post_chat(request: Request) -> Any:
    if _openai_key_missing():
        logger.warning("POST /chat 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        _mcp_rule_hit_from_chat_messages(messages_d),
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
        return _handle_unknown(e)


@router.post("")  # Next 对齐：`POST /api/test-case-agent`（无尾部斜杠）
@router.post("/")  # 同上能力：`POST .../test-case-agent/`（带斜杠）；兼容 `location .../test-case-agent/` 只转发此类路径的网关
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
    if _openai_key_missing():
        logger.warning("POST /api/test-case-agent 拒绝: 未配置 OPENAI_API_KEY")
        return _err_500_key()
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
        return _handle_unknown(e)


@router.post("/export-xmind")
async def post_export_xmind(request: Request) -> Any:
    """不要求 OPENAI_API_KEY（对齐现网）。"""
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /export-xmind JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})
    try:
        req = ExportXmindRequest.model_validate(body)
    except ValidationError:
        logger.warning("POST /export-xmind 参数校验失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    mind_dict = req.mind_map.model_dump(mode="python")
    cases_dicts: list[dict[str, Any]] | None = None
    if req.test_cases:
        cases_dicts = [c.model_dump(by_alias=True) for c in req.test_cases]

    sheet_title = (req.title or "").strip() or (req.mind_map.data.text or "测试用例")

    logger.info(
        "POST /export-xmind 开始 title=%s cases=%s",
        sheet_title[:80],
        len(cases_dicts or []),
    )
    try:
        blob = build_xmind_zip(mind_dict, cases_dicts, req.title)
        logger.info("POST /export-xmind 成功 bytes=%s", len(blob))
    except Exception as e:
        logger.exception("POST /export-xmind 失败: %s", e)
        return _handle_unknown(e)

    return Response(
        content=blob,
        media_type="application/vnd.xmind.workbook",
        headers={"Content-Disposition": content_disposition_filename(sheet_title)},
    )
