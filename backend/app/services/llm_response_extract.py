"""
从模型 / Agent 返回结果中取文本，并从带 markdown 的回复中剪出 JSON 对象串。
对齐 next-ai-test-cases `src/lib/agent/testCaseAgent.ts` 约 481–534 行。
"""

from __future__ import annotations

import re
from typing import Any


def agent_state_dict_from_invoke_result(agent_result: Any) -> dict[str, Any] | None:
    """将 LangGraph ``ainvoke`` 结果规范为含 ``messages`` 的状态 dict（若有）。

    LangGraph v2 可能返回 ``GraphOutput(value=state_dict, ...)``；消息项也可能是
    ``(BaseMessage, metadata)`` 元组，调用方需再归一化。
    ``value`` 偶现为带 ``messages`` 属性的非 dict（如状态模型），此处一并兼容。
    """
    if agent_result is None:
        return None
    if isinstance(agent_result, dict):
        return agent_result
    val = getattr(agent_result, "value", None)
    if isinstance(val, dict):
        return val
    if val is not None:
        msgs = getattr(val, "messages", None)
        if isinstance(msgs, list):
            return {"messages": msgs}
    return None


_JSON_FENCED = re.compile(r"```json\s*([\s\S]*?)```", re.IGNORECASE)
_ANY_FENCED = re.compile(r"```([\s\S]*?)```")


def _blocks_to_text(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
        else:
            parts.append("")
    return "\n".join(parts).strip()


def extract_text_from_agent_result(result: Any) -> str:
    """取 Agent `invoke` 结果里最后一条 `messages[-1].content`（约 481–502）。"""
    result = agent_state_dict_from_invoke_result(result)
    if not result:
        return ""

    messages_any = result.get("messages")
    if not isinstance(messages_any, list) or not messages_any:
        return ""

    last = _normalize_message_sequence_item(messages_any[-1])
    if isinstance(last, dict):
        content = last.get("content")
    else:
        content = getattr(last, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return _blocks_to_text(content)

    return ""


def extract_text_from_model_response(result: Any) -> str:
    """取 `model.invoke` 单条结果的 `content`；否则退回 `extract_text_from_agent_result`（约 505–524）。"""
    content: Any
    if isinstance(result, dict):
        content = result.get("content")
    else:
        content = getattr(result, "content", None)

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return _blocks_to_text(content)

    return extract_text_from_agent_result(result)


def _normalize_message_content_for_dump(value: Any) -> Any:
    """将 ToolMessage.content 转为可 ``json.dumps`` 的结构。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _normalize_message_content_for_dump(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_message_content_for_dump(v) for v in value]
    return str(value)


def _normalize_message_sequence_item(entry: Any) -> Any:
    """LangGraph 流式/状态里常见 ``(message, metadata)``，只取消息本体。"""
    if isinstance(entry, tuple) and entry:
        return entry[0]
    return entry


def collect_tool_messages_from_agent_result(agent_result: Any) -> list[dict[str, Any]]:
    """
    从 Agent ``ainvoke`` 返回值的 ``messages`` 中抽出 ``ToolMessage`` 条目（name + content），
    即经 LangChain 转手的 **MCP 工具原始返回**（如飞书 docx/wiki 工具的正文或 JSON 字符串）。
    """
    from langchain_core.messages import ToolMessage
    from langchain_core.messages.base import BaseMessage
    from langchain_core.messages.utils import convert_to_messages

    state = agent_state_dict_from_invoke_result(agent_result)
    if not state:
        return []
    msgs = state.get("messages")
    if not isinstance(msgs, list):
        return []

    out: list[dict[str, Any]] = []
    for i, raw in enumerate(msgs):
        m = _normalize_message_sequence_item(raw)
        candidates: list[Any]
        if isinstance(m, BaseMessage):
            candidates = [m]
        else:
            try:
                candidates = convert_to_messages([m])
            except Exception:
                candidates = [m]

        for cand in candidates:
            name: str | None
            tool_call_id: str | None
            content: Any

            if isinstance(cand, ToolMessage):
                name = cand.name
                tool_call_id = cand.tool_call_id
                content = cand.content
            elif isinstance(cand, BaseMessage) and getattr(cand, "type", None) == "tool":
                name = getattr(cand, "name", None)
                tool_call_id = getattr(cand, "tool_call_id", None)
                content = cand.content
            elif isinstance(cand, dict):
                mtype = cand.get("type")
                role = cand.get("role")
                inner = cand.get("data")
                if isinstance(inner, ToolMessage):
                    name = inner.name
                    tool_call_id = inner.tool_call_id
                    content = inner.content
                elif isinstance(inner, BaseMessage) and getattr(inner, "type", None) == "tool":
                    name = getattr(inner, "name", None)
                    tool_call_id = getattr(inner, "tool_call_id", None)
                    content = inner.content
                elif isinstance(inner, dict) and (
                    inner.get("type") == "tool" or inner.get("role") == "tool"
                ):
                    name = inner.get("name")
                    tool_call_id = inner.get("tool_call_id")
                    content = inner.get("content")
                elif mtype == "tool" or role == "tool":
                    if isinstance(inner, dict):
                        name = inner.get("name")
                        tool_call_id = inner.get("tool_call_id")
                        content = inner.get("content")
                    else:
                        name = cand.get("name")
                        tool_call_id = cand.get("tool_call_id")
                        content = cand.get("content")
                else:
                    continue
            else:
                continue

            if tool_call_id is None and name is None and content is None:
                continue

            out.append(
                {
                    "index": i,
                    "name": name,
                    "tool_call_id": tool_call_id,
                    "content": _normalize_message_content_for_dump(content),
                }
            )
    return out


def extract_json_object(text: str) -> str:
    """
    先取 fenced 代码块（优先 ``json`，否则任意 fenced），再取首个 `{` 与最后一个 `}` 间子串；
    无合法括号对则退回 strip 后全文（约 526–534）。
    """
    m = _JSON_FENCED.search(text) or _ANY_FENCED.search(text)
    source = (m.group(1) if m else text).strip()
    start = source.find("{")
    end = source.rfind("}")
    if start >= 0 and end > start:
        return source[start : end + 1]
    return source
