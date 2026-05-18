"""
对齐 ``invokeStructuredWithMcp`` / ``invokeJsonWithMcp``（TS 约 541–635）。
依赖可选：未安装 ``langchain-mcp-adapters`` 或 MCP 异常时回退直连。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.services.llm_response_extract import (
    agent_state_dict_from_invoke_result,
    collect_tool_messages_from_agent_result,
    extract_json_object,
    extract_text_from_agent_result,
    extract_text_from_model_response,
)
from app.services.mcp_loader import (
    load_mcp_servers_config,
    mcp_system_prompt_suffix_for_user_prompt,
    should_use_mcp,
)

logger = logging.getLogger(__name__)

_StructT = TypeVar("_StructT", bound=BaseModel)


def _feishu_mcp_tool_error_middleware() -> Any:
    """MCP 工具抛错时改为 ToolMessage 文本，避免 LangGraph 中断；模型可读报错并重试或换工具。"""
    from langchain.agents.middleware import wrap_tool_call
    from langchain_core.messages import ToolMessage

    @wrap_tool_call
    async def _feishu_mcp_route_tool_errors_to_model(request: Any, handler: Any) -> Any:
        try:
            return await handler(request)
        except Exception as exc:
            tc = request.tool_call
            tid = str(tc.get("id") or "")
            nm = tc.get("name")
            return ToolMessage(
                content=(
                    "工具调用失败。请根据下列 MCP 报错修正参数后重试，或改用其他工具。\n"
                    "飞书知识库链接 URL 含路径 /wiki/ 时，优先使用 wiki_* 搜索/获取节点类工具，"
                    "勿随意混用不适合的云文档搜索工具。\n"
                    "在调用时同时走租户令牌和用户令牌都要去尝试，不行的原因是: 可能某些用户没有权限使用某些工具，但是租户有权限使用。\n"
                    "若调用 docx_builtin_search，参数 data.docs_types 数组中每一项必须是英文小写且仅限："
                    "doc、sheet、slides、bitable、mindnote、file（禁止 document/wiki/docx 等自造值）。\n\n"
                    f"{exc!s}"
                ),
                tool_call_id=tid,
                name=nm,
            )

    return _feishu_mcp_route_tool_errors_to_model


# MCP phase1 取证摘要过长时对 phase2 结构化上下文截断（避免撑爆上下文）
_DEFAULT_MCP_BRIEF_MAX_CHARS = 60_000


def sanitize_mcp_document_brief_text(text: str) -> str:
    """
    去掉 MCP / 飞书文档拉取结果里常见的**纯图像占位**（无实质需求文字），减轻对后续结构化生成的干扰。

    不删除正文中含「图片」字样的完整句子，仅删独立占位行与 markdown / HTML 图标签。
    """
    if not (text or "").strip():
        return (text or "").strip()

    s = text
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"!\[[^\]]*\]", "", s)
    s = re.sub(r"<img\b[^>]*>", "", s, flags=re.IGNORECASE)
    _line_image_only = re.compile(
        r"^\s*(?:"
        r"\[图片\]|【图片】|\(图片\)|（图片）|"
        r"图像占位|图片占位|"
        r"(?:图片|图像|截图|插图|附图)\s*[：:]?\s*$|"
        r"Figure\s*\d*\s*[：:]?\s*$|"
        r"IMAGE\s*$|IMG\s*$"
        r")\s*$",
        re.IGNORECASE,
    )

    out_lines = [ln for ln in s.splitlines() if not _line_image_only.match(ln)]
    s = "\n".join(out_lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _log_mcp_requirement_doc_phase1(*, log_prefix: str, research: str) -> None:
    """phase1 结束后：区分「拿到可引用摘要」与「未拿到正文」。"""
    n = len((research or "").strip())
    if n > 0:
        logger.info("%s MCP读需求文档 成功 phase1 已返回取证摘要 research_chars=%s", log_prefix, n)
    else:
        logger.warning(
            "%s MCP读需求文档 失败 phase1 无有效摘要（可能未调用读文档工具、工具报错/无权限、或模型未输出）",
            log_prefix,
        )


def _agent_reply_text(result: Any) -> str:
    """AgentState：兼容 ``messages[-1]`` 为 dict 或 LangChain Message 对象。"""
    text = extract_text_from_agent_result(result)
    if text.strip():
        return text
    state = agent_state_dict_from_invoke_result(result)
    if not state:
        return ""
    msgs = state.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return ""
    last = msgs[-1]
    if isinstance(last, tuple) and last:
        last = last[0]
    content: Any = last.get("content") if isinstance(last, dict) else getattr(last, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "\n".join(parts).strip()
    return ""


# 与 merge 中占位摘要句首一致，用于判断是否启用 MCP phase2 强文档锚定块
_MCP_PLACEHOLDER_BRIEF_PREFIX = "（本次未通过 MCP"

_MCP_PHASE2_STRONG_DOC_ANCHOR = """## 文档锚定（结构化产出硬性约束，优先于下文「多产/全覆盖」等笼统表述）

1. **事实来源**：紧挨上文的「MCP 查证摘要」是需求事实的首要来源；模块拆分、用例的 topic、steps、expected 中的业务对象、状态、规则、数字阈值、渠道/平台名等，须能在摘要中找到依据或忠实转述。
2. **禁止编造**：不得引入摘要未提及的功能、接口字段、枚举、回调、权限模型；禁止为用例数量达标而堆叠与文档无关的「通用模板」场景。
3. **冲突处理**：若下方「用户任务」中的文字与摘要矛盾，**以摘要为准**。
4. **术语**：宜沿用摘要中的专有名词，便于与需求逐条对照。
5. **仍缺细节**：仅在 summary 中列出「文档未写明」的缺口；可做最小假设的须标明「假设」，且不得显著扩张需求范围。"""

_MCP_PHASE2_WEAK_DOC_ANCHOR = """## 说明

当前未拿到可引用的外链文档正文（或仅为拉取失败说明）。请主要依据下方「用户任务」作答；信息不足时可在 summary 说明假设，避免编造文档中未出现的复杂规则。"""


def merge_mcp_research_into_task_prompt(
    original_prompt: str,
    mcp_research_text: str,
    *,
    max_brief_chars: int = _DEFAULT_MCP_BRIEF_MAX_CHARS,
) -> str:
    """
    MCP phase1 仅产出自然语言取证摘要；与用户原始任务拼接后，
    由 phase2 ``with_structured_output`` 生成合法 JSON Schema 对象。
    """
    brief = sanitize_mcp_document_brief_text((mcp_research_text or "").strip())
    if not brief:
        brief = (
            "（本次未通过 MCP 拿到可引用的外链文档正文，可能未调用工具、权限不足或无链接。"
            "请依据下方「用户任务」中的文字与链接描述作答。）"
        )
    elif len(brief) > max_brief_chars:
        brief = brief[:max_brief_chars] + "\n\n…（以上 MCP 取证内容已截断）…"

    use_strong_anchor = not brief.startswith(_MCP_PLACEHOLDER_BRIEF_PREFIX)
    anchor_block = _MCP_PHASE2_STRONG_DOC_ANCHOR if use_strong_anchor else _MCP_PHASE2_WEAK_DOC_ANCHOR

    return (
        "## MCP 查证摘要（来自工具调用的文档或知识库要点）\n\n"
        f"{brief}\n\n"
        f"{anchor_block}\n\n"
        "---\n\n"
        "## 用户任务与输出要求（须完整遵守，生成结构化结果）\n\n"
        f"{original_prompt.strip()}"
    )


# MCP phase1（取证）：只取证，禁止输出 JSON（避免 Agent 乱序/未转义引号导致解析失败）。
MCP_STRUCTURED_PHASE1_SYSTEM_PROMPT = (
    "你是文档与需求取证助手，须**尽最大可能**调用 MCP 工具读取用户消息中的飞书/钉钉/知识库/wiki 正文；"
    "在存在可识别协议链接或文档 token 时，**禁止**在未实际调用读文档类工具前假装已阅读原文。\n"
    "回复仅用自然语言（可分小节），**禁止** JSON、**禁止** markdown 代码围栏、**禁止**输出测试用例/脑图/结构化表格。\n\n"
    "**飞书工具参数（硬性）**：URL 含「/wiki/」的知识库/wiki 页面，优先选用名称含 wiki 的工具检索或取节点；"
    "若使用 docx_builtin_search，参数 data.docs_types 仅允许（英文小写）：doc、sheet、slides、bitable、mindnote、file；"
    "不得使用 document、wiki、docx 等非枚举值。工具返回报错时必须阅读报错并修正后再调用。\n\n"
    "建议输出结构（可按文档实际内容增删小节标题，但须尽量保留原文措辞与数字）：\n"
    "【文档概览】文档标题或主题一句；\n"
    "【背景与目标】原文要点；\n"
    "【需求与规则】逐条列出可测的业务规则、流程步骤、状态迁移、计算公式或策略（尽量保留专名、数字、枚举取值）；\n"
    "【边界、异常与兼容】原文明确写出的失败场景、重试、降级、版本或环境约束；\n"
    "【术语与非目标】关键名词表；若文档写明「不做/不在范围」须单独列出。\n\n"
    "**关于文档内图片**：正文旁的示意图、截图若仅有占位符（如 [图片]、markdown 图链、无文字说明），"
    "不要在摘要中复述这些占位；若某张图旁有**文字标题或说明**，请保留该文字；"
    "需求信息以可测的文字描述为准。\n\n"
    "质量要求：多用摘录与转述，少写空话；若工具报错或无权限，明确写出错误信息与仍拿到的片段长度；不要泛泛概括代替原文。"
)

MCP_CHAT_PHASE1_SYSTEM_PROMPT = (
    "你是测试用例脑图相关的文档取证助手，须通过 MCP 工具**实际读取**用户提到的飞书/钉钉/知识库正文后再作答。\n"
    "仅用自然语言回复：用户意图、应从文档采纳的关键需求、对脑图调整的建议；**禁止** JSON、代码围栏、mindMap。\n"
    "飞书 URL 含 /wiki/ 时优先 wiki 类工具；docx_builtin_search 的 data.docs_types 仅允许："
    "doc、sheet、slides、bitable、mindnote、file（英文小写）。\n"
    "建议分【文档要点摘录】【与脑图相关的增量信息】【工具/拉取异常说明（若有）】；摘录尽量保留原文专名与数字。\n"
    "文档中纯图片占位（无旁文）请勿写入摘录；图侧有标题/说明文字则保留文字。"
)


async def try_mcp_phase1_structured_document_research(
    model: BaseChatModel,
    user_prompt_content: str,
    *,
    log_prefix: str,
) -> tuple[bool, str, list[dict[str, Any]] | None]:
    """
    MCP 结构化链路的 Phase1-only（与本文件 ``invoke_structured_with_mcp`` 完全一致的前置门禁与 Agent）。

    返回 ``(mcp_lane_ok, research_text, tool_raw_messages)``：

    - ``mcp_lane_ok=False``：未形成 MCP Agent 链路（应走全流程 ``_fallback_structured``）；
    - ``mcp_lane_ok=True``：已进入 Phase1 Agent；``research_text`` 可能为空字符串，但若走 lane 仍会经
      ``merge_mcp_research_into_task_prompt`` 用占位摘要进入 Phase2。
    - ``tool_raw_messages``：本条 Phase1 中从 Agent 状态抽取的 MCP 工具原始返回列表；lane 未建立时为 ``None``。
    """
    prompt = user_prompt_content
    if not should_use_mcp(prompt):
        logger.info("%s MCP Phase1 未尝试 原因=no_rule_match prompt_chars=%s", log_prefix, len(prompt or ""))
        return (False, "", None)
    connections = load_mcp_servers_config()
    if not connections:
        logger.info("%s MCP Phase1 未尝试 原因=no_mcp_json_servers", log_prefix)
        return (False, "", None)

    try:
        from langchain.agents import create_agent
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("%s MCP Phase1 失败 langchain-mcp-adapters 未安装", log_prefix)
        return (False, "", None)

    client = MultiServerMCPClient(connections)
    try:
        tools = await client.get_tools()
    except Exception as exc:
        logger.warning("%s MCP Phase1 失败 get_tools 异常 err=%s", log_prefix, exc, exc_info=True)
        return (False, "", None)

    if not tools:
        logger.warning("%s MCP Phase1 失败 MCP 返回 tools 为空", log_prefix)
        return (False, "", None)

    tool_names = [getattr(t, "name", str(t)) for t in tools[:24]]
    logger.info("%s MCP Phase1 tools=%s 示例=%s", log_prefix, len(tools), tool_names)

    try:
        agent = create_agent(
            model,
            tools,
            system_prompt=MCP_STRUCTURED_PHASE1_SYSTEM_PROMPT
            + mcp_system_prompt_suffix_for_user_prompt(prompt),
            middleware=[_feishu_mcp_tool_error_middleware()],
        )
        t0 = time.perf_counter()
        logger.info(
            "%s MCP Phase1 开始 Agent+MCP取证 prompt_chars=%s tools=%s",
            log_prefix,
            len(prompt or ""),
            len(tools),
        )
        result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})
        research = sanitize_mcp_document_brief_text((_agent_reply_text(result) or "").strip())
        tool_raw = collect_tool_messages_from_agent_result(result)
        t1 = time.perf_counter()
        logger.info(
            "%s MCP Phase1 结束 elapsed_ms=%s research_chars=%s tool_messages=%s",
            log_prefix,
            int((t1 - t0) * 1000),
            len(research),
            len(tool_raw),
        )
        _log_mcp_requirement_doc_phase1(log_prefix=log_prefix, research=research)
        return (True, research, tool_raw)
    except Exception as exc:
        logger.warning(
            "%s MCP Phase1 Agent 异常，视为未建立 MCP lane err=%s", log_prefix, exc, exc_info=True
        )
        return (False, "", None)


async def _fallback_structured(
    model: BaseChatModel,
    prompt: str,
    schema_cls: type[_StructT],
    schema_constant: str,
) -> _StructT:
    logger.info(
        "structured[%s]: 步骤=直连结构化(prompt_structured兜底) prompt_chars=%s",
        schema_constant,
        len(prompt or ""),
    )
    from app.services.test_case_llm import _ainvoke_schema_or_markdown_json

    return await _ainvoke_schema_or_markdown_json(model, prompt, schema_cls, schema_constant)


async def invoke_structured_with_mcp(
    model: BaseChatModel,
    prompt: str,
    schema_cls: type[_StructT],
    schema_constant: str,
    *,
    prefetched_research: str | None = None,
) -> tuple[_StructT, str | None]:
    """
    返回 (结构化结果, phase1_natural_language_research)。

    - 若本次完整跑通 MCP phase1，返回元组的第二元素为 Agent 取证正文，可供后续 /module 复用；
    - 若使用 ``prefetched_research`` 或未走 MCP，第二元素为 ``None``。
    """
    prefetch = (prefetched_research or "").strip()
    if prefetch:
        from app.services.test_case_llm import _ainvoke_prompt_structured

        logger.info(
            "structured[%s]: MCP决策=复用prefetch 跳过phase1 prefetch_chars=%s → 仅phase2",
            schema_constant,
            len(prefetch),
        )
        logger.info(
            "structured[%s]: MCP读需求文档 跳过 使用上游缓存 mcpDocumentBrief chars=%s",
            schema_constant,
            len(prefetch),
        )
        merged = merge_mcp_research_into_task_prompt(prompt, prefetch)
        validated = await _ainvoke_prompt_structured(
            model, merged, schema_cls, schema_constant
        )
        return (validated, None)

    lane_ok, research, _tool_raw_unused = await try_mcp_phase1_structured_document_research(
        model, prompt, log_prefix=f"structured[{schema_constant}]:",
    )
    if not lane_ok:
        logger.info(
            "structured[%s]: MCP_lane 不可用或 Phase1 未成功 → _fallback_structured",
            schema_constant,
        )
        val = await _fallback_structured(model, prompt, schema_cls, schema_constant)
        return (val, None)

    try:
        merged = merge_mcp_research_into_task_prompt(prompt, research)
        logger.info(
            "structured[%s]: MCP phase2 开始(with_structured_output) merged_prompt_chars=%s",
            schema_constant,
            len(merged or ""),
        )
        from app.services.test_case_llm import _ainvoke_prompt_structured

        t2 = time.perf_counter()
        validated = await _ainvoke_prompt_structured(model, merged, schema_cls, schema_constant)
        t3 = time.perf_counter()
        logger.info(
            "structured[%s]: MCP phase2 结束 elapsed_ms=%s MCP取证+结构化全流程成功",
            schema_constant,
            int((t3 - t2) * 1000),
        )
        research_out = research if research else None
        if research_out:
            logger.info(
                "structured[%s]: MCP读需求文档 成功 phase1 有可下发 mcpDocumentBrief",
                schema_constant,
            )
        return (validated, research_out)
    except Exception as exc:
        logger.warning(
            "structured[%s]: MCP Phase2 异常，回退直连 prompt_chars=%s err=%s",
            schema_constant,
            len(prompt or ""),
            exc,
            exc_info=True,
        )
        val = await _fallback_structured(model, prompt, schema_cls, schema_constant)
        return (val, None)


async def _fallback_chat_json(model: BaseChatModel, prompt: str) -> dict[str, Any]:
    from app.schemas.llm_output import ChatStructuredOutput
    from app.services import test_case_agent as tca

    logger.info(
        "chat_json: 步骤=直连(无MCP或未启用) prompt_chars=%s",
        len(prompt or ""),
    )
    raw = await model.ainvoke(prompt)
    text = extract_text_from_model_response(raw)
    blob = extract_json_object(text)
    data = json.loads(blob)
    parsed = ChatStructuredOutput.model_validate(data)
    mind_dict = parsed.mindMap.model_dump(mode="python")
    mind_norm = tca.normalize_parsed_mind_map(mind_dict)
    return {
        "assistantReply": parsed.assistantReply,
        "mindMap": mind_norm,
    }


async def invoke_json_with_mcp(model: BaseChatModel, prompt: str) -> dict[str, Any]:
    """
    对齐 ``invokeJsonWithMcp``：chat 路径；最终结构与 ``chat_and_update_mind_map`` 一致。
    """
    if not should_use_mcp(prompt):
        logger.info(
            "chat_json: MCP决策=否 原因=no_rule_match prompt_chars=%s → 直连",
            len(prompt or ""),
        )
        return await _fallback_chat_json(model, prompt)

    connections = load_mcp_servers_config()
    if not connections:
        logger.info(
            "chat_json: MCP决策=否 原因=no_mcp_json_servers prompt_chars=%s → 直连",
            len(prompt or ""),
        )
        return await _fallback_chat_json(model, prompt)

        logger.info(
            "chat_json: MCP路径=research_then_json_schema servers=%s",
            list(connections.keys()),
        )

    try:
        from langchain.agents import create_agent
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("chat_json: MCP读需求文档 失败 langchain-mcp-adapters 未安装，已跳过 MCP 直连 chat")
        return await _fallback_chat_json(model, prompt)

    client = MultiServerMCPClient(connections)
    try:
        tools = await client.get_tools()
    except Exception as exc:
        logger.warning(
            "chat_json: MCP读需求文档 失败 get_tools 异常，已回退 chat 直连 err=%s",
            exc,
            exc_info=True,
        )
        return await _fallback_chat_json(model, prompt)

    if not tools:
        logger.warning("chat_json: MCP读需求文档 失败 MCP 返回 tools 为空，已回退 chat 直连")
        return await _fallback_chat_json(model, prompt)

    tool_names = [getattr(t, "name", str(t)) for t in tools[:24]]
    logger.info("chat_json: MCP tools 数量=%s 示例=%s", len(tools), tool_names)

    try:
        agent = create_agent(
            model,
            tools,
            system_prompt=MCP_CHAT_PHASE1_SYSTEM_PROMPT
            + mcp_system_prompt_suffix_for_user_prompt(prompt),
            middleware=[_feishu_mcp_tool_error_middleware()],
        )
        t0 = time.perf_counter()
        logger.info(
            "chat_json: MCP phase1 开始(Agent+MCP取证) prompt_chars=%s tools=%s",
            len(prompt or ""),
            len(tools),
        )
        result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})
        research = sanitize_mcp_document_brief_text((_agent_reply_text(result) or "").strip())
        t1 = time.perf_counter()
        logger.info(
            "chat_json: MCP phase1 结束 elapsed_ms=%s research_chars=%s",
            int((t1 - t0) * 1000),
            len(research or ""),
        )
        _log_mcp_requirement_doc_phase1(log_prefix="chat_json:", research=research)

        merged = merge_mcp_research_into_task_prompt(prompt, research)
        logger.info(
            "chat_json: MCP phase2 开始(with_structured_output) merged_prompt_chars=%s",
            len(merged or ""),
        )
        from app.schemas.llm_output import CHAT_SCHEMA_NAME, ChatStructuredOutput
        from app.services import test_case_agent as tca
        from app.services.test_case_llm import _ainvoke_prompt_structured

        t2 = time.perf_counter()
        parsed = await _ainvoke_prompt_structured(
            model, merged, ChatStructuredOutput, CHAT_SCHEMA_NAME
        )
        t3 = time.perf_counter()
        logger.info(
            "chat_json: MCP phase2 结束 elapsed_ms=%s MCP取证+结构化全流程成功 total_elapsed_ms=%s",
            int((t3 - t2) * 1000),
            int((t3 - t0) * 1000),
        )
        if (research or "").strip():
            logger.info(
                "chat_json: MCP读需求文档 成功 取证与结构化收口已完成且 phase1 有取证摘要"
            )
        mind_dict = parsed.mindMap.model_dump(mode="python")
        mind_norm = tca.normalize_parsed_mind_map(mind_dict)
        return {
            "assistantReply": parsed.assistantReply,
            "mindMap": mind_norm,
        }
    except Exception as exc:
        logger.warning(
            "chat_json: MCP读需求文档 失败 phase1/phase2 执行异常，回退 chat 直连 prompt_chars=%s err=%s",
            len(prompt or ""),
            exc,
            exc_info=True,
        )
        return await _fallback_chat_json(model, prompt)
