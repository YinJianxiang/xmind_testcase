"""
§6.5 / §6.6 / §6.7：结构化 invoke；prompt 命中 MCP 规则且 ``mcp.json`` 可用时走 Agent+MCP（对齐 TS ``invokeStructuredWithMcp`` / ``invokeJsonWithMcp``），否则直连 ``with_structured_output`` / ``model.ainvoke``。
对齐 `testCaseAgent.ts` 中 `planTestCaseModules` / `generateTestCases` /
`generateModuleTestCases` / `chatAndUpdateMindMap`。
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from app.schemas.llm_output import (
    GENERATION_SCHEMA_NAME,
    MODULE_GENERATION_SCHEMA_NAME,
    PLAN_SCHEMA_NAME,
    GenerationStructuredOutput,
    PlanStructuredOutput,
    coerce_plan_llm_dict,
)
from app.services import test_case_agent as tca
from app.services.chat_model import create_chat_model
from app.services.llm_response_extract import (
    extract_json_object,
    extract_text_from_model_response,
)
from app.services.mcp_loader import load_mcp_servers_config, should_use_mcp
from app.services.test_case_mcp_invoke import invoke_json_with_mcp, invoke_structured_with_mcp


logger = logging.getLogger(__name__)
_StructT = TypeVar("_StructT", bound=BaseModel)


def _coerce_parsed_dict(schema_cls: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    if schema_cls is PlanStructuredOutput:
        return coerce_plan_llm_dict(data)
    return data


def _structured_runnable(
    model: BaseChatModel, schema_cls: type[BaseModel], _schema_name: str
):
    """Structured output with method='json_schema'.

    Retain third arg for call-site parity with TS constants (PLAN_SCHEMA_NAME, …); do not pass
    LangChain/OpenAI top-level ``name`` — langchain-openai may call ``chat.completions.parse``,
    which rejects that keyword at the top level.
    """
    return model.with_structured_output(schema_cls, method="json_schema")


async def _ainvoke_prompt_structured(
    model: BaseChatModel,
    prompt: str,
    schema_cls: type[_StructT],
    schema_constant: str,
) -> _StructT:
    """
    对任意完整任务 prompt 走结构化：先 ``with_structured_output``，失败则 raw 正文 → ``extract_json_object``。

    供直连与 MCP 二阶段收口复用（MCP 路径在 Agent 取证后传入合并后的 prompt）。
    """
    chain = _structured_runnable(model, schema_cls, schema_constant)
    try:
        out = await chain.ainvoke(prompt)
        if isinstance(out, schema_cls):
            logger.info(
                "prompt_structured[%s]: with_structured_output 首轮成功 prompt_chars=%s",
                schema_constant,
                len(prompt or ""),
            )
            return out
        if isinstance(out, dict):
            logger.info(
                "prompt_structured[%s]: 首轮返回 dict 已校验 prompt_chars=%s",
                schema_constant,
                len(prompt or ""),
            )
            return schema_cls.model_validate(_coerce_parsed_dict(schema_cls, out))
        if isinstance(out, str):
            dct = json.loads(extract_json_object(out))
            logger.info(
                "prompt_structured[%s]: 首轮返回 str 解析 JSON 成功 prompt_chars=%s",
                schema_constant,
                len(prompt or ""),
            )
            return schema_cls.model_validate(_coerce_parsed_dict(schema_cls, dct))
    except Exception as first_exc:
        logger.info(
            "结构化输出首轮失败，尝试 markdown JSON 兜底 schema=%s err=%s",
            schema_constant,
            first_exc,
        )
    raw_msg = await model.ainvoke(prompt)
    text = extract_text_from_model_response(raw_msg)
    blob = extract_json_object(text)
    data = json.loads(blob)
    logger.info(
        "prompt_structured[%s]: markdown/原文 JSON 兜底成功 prompt_chars=%s",
        schema_constant,
        len(prompt or ""),
    )
    return schema_cls.model_validate(_coerce_parsed_dict(schema_cls, data))


async def _ainvoke_schema_or_markdown_json(
    model: BaseChatModel,
    prompt: str,
    schema_cls: type[_StructT],
    schema_constant: str,
) -> _StructT:
    """
    先走 ``with_structured_output``；若网关/兼容接口仍返回带 markdown 代码块的正文（或链路解析失败），
    与同文件 ``chat_and_update_mind_map`` 一致：正文 → ``extract_json_object`` → JSON → Pydantic。
    """
    return await _ainvoke_prompt_structured(model, prompt, schema_cls, schema_constant)


async def plan_test_case_modules(
    requirement: str,
    *,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """682–710：plan 结构化输出 → `normalize_modules` → `build_skeleton_mind_map`。"""
    model = llm or create_chat_model()
    logger.info(
        "plan_test_case_modules: 阶段=模块规划 步骤=初始化模型 schema=%s",
        PLAN_SCHEMA_NAME,
    )
    prompt = tca.build_plan_test_case_modules_prompt(requirement)
    mcp_servers = load_mcp_servers_config()
    logger.info(
        "plan_test_case_modules: 步骤=构建 prompt 完成 prompt_chars=%s mcp_rule_hit=%s mcp_config_servers=%s",
        len(prompt),
        should_use_mcp(prompt),
        list(mcp_servers.keys()) if mcp_servers else [],
    )
    parsed, mcp_phase1_research = await invoke_structured_with_mcp(
        model, prompt, PlanStructuredOutput, PLAN_SCHEMA_NAME
    )
    logger.info(
        "plan_test_case_modules: 步骤=结构化解析完成 modules_raw=%s summary_chars=%s",
        len(parsed.modules),
        len(parsed.summary or ""),
    )
    raw_modules = [m.model_dump() for m in parsed.modules]
    modules_norm = tca.normalize_modules(raw_modules)
    mind_map = tca.build_skeleton_mind_map(modules_norm)
    sk_children = mind_map.get("children") if isinstance(mind_map, dict) else None
    logger.info(
        "plan_test_case_modules: 完成 阶段=模块规划 modules=%s skeleton_children=%s summary_chars=%s",
        len(modules_norm),
        len(sk_children) if isinstance(sk_children, list) else 0,
        len(parsed.summary or ""),
    )
    out: dict[str, Any] = {
        "summary": parsed.summary,
        "modules": modules_norm,
        "mindMap": mind_map,
    }
    brief = (mcp_phase1_research or "").strip()
    if brief:
        out["mcpDocumentBrief"] = brief
    return out


async def fetch_plan_mcp_document_brief(
    requirement: str,
    *,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """
    MCP Phase1-only：与用户消息一致，送入 ``build_plan_test_case_modules_prompt`` 再走取证 Agent。
    返回 ``{\"mcpDocumentBrief\": \"...\", \"mcpDocumentToolRaw\": [...] | null}``
    （不可用或未跑通 MCP lane 时 brief 为 ``\"\"``、``mcpDocumentToolRaw`` 为 ``null``）。
    """
    model = llm or create_chat_model()
    prompt = tca.build_plan_test_case_modules_prompt(requirement)
    logger.info(
        "fetch_plan_mcp_document_brief: 步骤=仅Phase1 MCP prompt_chars=%s mcp_rule_hit=%s",
        len(prompt),
        should_use_mcp(prompt),
    )
    from app.services.test_case_mcp_invoke import try_mcp_phase1_structured_document_research

    _, brief, tool_raw = await try_mcp_phase1_structured_document_research(
        model, prompt, log_prefix="plan/requirement-source:"
    )
    return {"mcpDocumentBrief": brief, "mcpDocumentToolRaw": tool_raw}


async def plan_modules_without_skeleton(
    requirement: str,
    *,
    mcp_document_brief: str | None = None,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """
    Plan Phase2-ish：结构化输出模块列表并可复用 prefetch（与 MCP 二阶段对齐）。
    不含 ``mindMap``。
    """
    model = llm or create_chat_model()
    prompt = tca.build_plan_test_case_modules_prompt(requirement)
    mcp_servers = load_mcp_servers_config()
    prefetch: str | None = None
    if mcp_document_brief is not None and str(mcp_document_brief).strip():
        prefetch = str(mcp_document_brief).strip()
    logger.info(
        "plan_modules_without_skeleton: prompt_chars=%s mcp_prefetch_chars=%s mcp_servers=%s",
        len(prompt),
        len(prefetch or ""),
        list(mcp_servers.keys()) if mcp_servers else [],
    )
    parsed, _meta = await invoke_structured_with_mcp(
        model,
        prompt,
        PlanStructuredOutput,
        PLAN_SCHEMA_NAME,
        prefetched_research=prefetch,
    )
    raw_modules = [m.model_dump() for m in parsed.modules]
    modules_norm = tca.normalize_modules(raw_modules)
    return {"summary": parsed.summary, "modules": modules_norm}


def plan_skeleton_mind_map_only(modules_payload: list[dict[str, Any]]) -> dict[str, Any]:
    """由 ``normalize_modules`` + ``build_skeleton_mind_map`` 生成脑图，无 LLM 调用。"""
    from app.schemas.mindmap import MindMapNode

    modules_norm = tca.normalize_modules(modules_payload)
    mind_map = tca.build_skeleton_mind_map(modules_norm)
    MindMapNode.model_validate(mind_map)
    return {"mindMap": mind_map}


async def generate_test_cases(
    requirement: str,
    *,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """638–680：generation → `normalize_cases` → `build_mind_map_from_cases`。"""
    model = llm or create_chat_model()
    logger.info(
        "generate_test_cases: 阶段=全文用例生成 步骤=初始化模型 schema=%s",
        GENERATION_SCHEMA_NAME,
    )
    prompt = tca.build_generate_test_cases_prompt(requirement)
    mcp_servers = load_mcp_servers_config()
    logger.info(
        "generate_test_cases: 步骤=构建 prompt 完成 prompt_chars=%s mcp_rule_hit=%s mcp_config_servers=%s",
        len(prompt),
        should_use_mcp(prompt),
        list(mcp_servers.keys()) if mcp_servers else [],
    )
    logger.info(
        "generate_test_cases: 步骤=invoke_structured 开始 schema=%s (内部可按 MCP 两阶段)",
        GENERATION_SCHEMA_NAME,
    )
    parsed, _ = await invoke_structured_with_mcp(
        model, prompt, GenerationStructuredOutput, GENERATION_SCHEMA_NAME
    )
    logger.info(
        "generate_test_cases: 步骤=invoke_structured 结束 LLM_cases=%s summary_chars=%s",
        len(parsed.cases),
        len(parsed.summary or ""),
    )
    logger.info(
        "generate_test_cases: 步骤=model_dump 转成 dict 条目=%s",
        len(parsed.cases),
    )
    raw_cases = [c.model_dump() for c in parsed.cases]
    logger.info(
        "generate_test_cases: 步骤=normalize_cases 开始 input=%s",
        len(raw_cases),
    )
    cases_norm = tca.normalize_cases(raw_cases)
    dropped = len(raw_cases) - len(cases_norm)
    logger.info(
        "generate_test_cases: 步骤=normalize_cases 完成 output=%s dedupe_dropped=%s",
        len(cases_norm),
        dropped,
    )
    logger.info("generate_test_cases: 步骤=build_mind_map_from_cases 开始")
    mind_map = tca.build_mind_map_from_cases(cases_norm)
    root_children = mind_map.get("children") if isinstance(mind_map, dict) else None
    ncats = len(root_children) if isinstance(root_children, list) else 0
    logger.info(
        "generate_test_cases: 步骤=build_mind_map_from_cases 完成 root一级子节点(分类数)=%s",
        ncats,
    )
    logger.info(
        "generate_test_cases: 完成 阶段=全文用例生成 cases=%s mind_map_built=1",
        len(cases_norm),
    )
    return {
        "summary": parsed.summary,
        "cases": cases_norm,
        "mindMap": mind_map,
    }


async def generate_module_test_cases(
    requirement: str,
    module: tca.TestCaseModulePlan,
    modules: list[tca.TestCaseModulePlan],
    *,
    llm: BaseChatModel | None = None,
    mcp_document_brief: str | None = None,
) -> dict[str, Any]:
    """712–757：同 generation schema → `normalize_module_cases` → `build_module_mind_map_from_cases`。"""
    model = llm or create_chat_model()
    title = str(module.get("title") or "") if isinstance(module, dict) else ""
    logger.info(
        "generate_module_test_cases: 阶段=单模块用例 步骤=初始化 model module=%s modules_total=%s schema=%s",
        title[:120],
        len(modules),
        MODULE_GENERATION_SCHEMA_NAME,
    )
    prompt = tca.build_generate_module_test_cases_prompt(requirement, module, modules)
    mcp_servers = load_mcp_servers_config()
    logger.info(
        "generate_module_test_cases: 步骤=构建 prompt 完成 prompt_chars=%s mcp_rule_hit=%s mcp_config_servers=%s",
        len(prompt),
        should_use_mcp(prompt),
        list(mcp_servers.keys()) if mcp_servers else [],
    )
    brief_in = (mcp_document_brief or "").strip()
    logger.info(
        "generate_module_test_cases: 步骤=invoke_structured 开始 schema=%s module=%s use_prefetch=%s",
        MODULE_GENERATION_SCHEMA_NAME,
        title[:120],
        bool(brief_in),
    )
    parsed, _ = await invoke_structured_with_mcp(
        model,
        prompt,
        GenerationStructuredOutput,
        MODULE_GENERATION_SCHEMA_NAME,
        prefetched_research=brief_in or None,
    )
    logger.info(
        "generate_module_test_cases: 步骤=invoke_structured 结束 LLM_cases=%s summary_chars=%s module=%s",
        len(parsed.cases),
        len(parsed.summary or ""),
        title[:120],
    )
    logger.info("generate_module_test_cases: 步骤=normalize_target_module 开始")
    target = tca.normalize_modules([module])[0]
    logger.info(
        "generate_module_test_cases: 步骤=normalize_target_module 完成 module_id=%s title=%s",
        str(target.get("id") or "")[:80],
        str(target.get("title") or "")[:120],
    )
    logger.info(
        "generate_module_test_cases: 步骤=model_dump 转成 dict 条目=%s",
        len(parsed.cases),
    )
    raw_cases = [c.model_dump() for c in parsed.cases]
    logger.info(
        "generate_module_test_cases: 步骤=normalize_module_cases 开始 input=%s",
        len(raw_cases),
    )
    cases_norm = tca.normalize_module_cases(target, raw_cases)
    dropped = len(raw_cases) - len(cases_norm)
    logger.info(
        "generate_module_test_cases: 步骤=normalize_module_cases 完成 output=%s shrink_vs_raw=%s",
        len(cases_norm),
        dropped,
    )
    logger.info(
        "generate_module_test_cases: 步骤=build_module_mind_map_from_cases 开始 module_id=%s",
        str(target.get("id") or "")[:80],
    )
    mind_map = tca.build_module_mind_map_from_cases(target, cases_norm)
    mod_children = mind_map.get("children") if isinstance(mind_map, dict) else None
    n_pre_groups = len(mod_children) if isinstance(mod_children, list) else 0
    logger.info(
        "generate_module_test_cases: 步骤=build_module_mind_map_from_cases 完成 前置条件分组数=%s",
        n_pre_groups,
    )
    logger.info(
        "generate_module_test_cases: 完成 阶段=单模块用例 module=%s cases=%s",
        title[:120],
        len(cases_norm),
    )
    return {
        "summary": parsed.summary,
        "module": target,
        "cases": cases_norm,
        "mindMap": mind_map,
    }


async def chat_and_update_mind_map(
    messages: list[Any],
    current_mind_map: dict[str, Any],
    *,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """
    763–795：`model.ainvoke` → 取文本 → `extract_json_object` → 校验 `ChatStructuredOutput` →
    `normalize_parsed_mind_map`。返回 camelCase 键（与 TS / 前端一致）。
    """
    model = llm or create_chat_model()
    logger.info(
        "chat_and_update_mind_map: 阶段=对话改脑图 步骤=初始化 messages=%s",
        len(messages),
    )
    prompt = tca.build_chat_and_update_mind_map_prompt(messages, current_mind_map)
    mcp_servers = load_mcp_servers_config()
    logger.info(
        "chat_and_update_mind_map: 步骤=构建 prompt 完成 prompt_chars=%s mcp_rule_hit=%s mcp_config_servers=%s",
        len(prompt),
        should_use_mcp(prompt),
        list(mcp_servers.keys()) if mcp_servers else [],
    )
    result = await invoke_json_with_mcp(model, prompt)
    logger.info(
        "chat_and_update_mind_map: 完成 阶段=对话改脑图 reply_chars=%s",
        len(str(result.get("assistantReply") or "")),
    )
    return result
