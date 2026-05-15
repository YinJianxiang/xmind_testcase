"""merge_mcp_research_into_task_prompt（MCP 二阶段拼接）单测。"""

from __future__ import annotations

import pytest

from app.services.llm_response_extract import collect_tool_messages_from_agent_result
from app.services.test_case_mcp_invoke import (
    _DEFAULT_MCP_BRIEF_MAX_CHARS,
    merge_mcp_research_into_task_prompt,
    sanitize_mcp_document_brief_text,
)


def test_sanitize_mcp_document_brief_text_removes_placeholders() -> None:
    raw = """首段需求说明

![alt](https://x/feishu/xyz.png)

[图片]

正文：按钮需校验
【图片】
"""
    out = sanitize_mcp_document_brief_text(raw)
    assert "![alt]" not in out
    assert "[图片]" not in out
    assert "【图片】" not in out
    assert "首段需求说明" in out
    assert "按钮需校验" in out


def test_merge_sanitizes_brief_before_embedding() -> None:
    orig = "TASK"
    brief = "摘录\n![x](y)\n[图片]\n有效句"
    merged = merge_mcp_research_into_task_prompt(orig, brief)
    assert "![x]" not in merged
    assert "[图片]" not in merged
    assert "有效句" in merged
    assert orig in merged


def test_collect_tool_messages_from_agent_result():
    from langchain_core.messages import HumanMessage, ToolMessage

    r = {
        "messages": [
            HumanMessage("hi"),
            ToolMessage('{"k":1}', tool_call_id="c1", name="docx_v1_document_rawContent"),
        ],
    }
    rows = collect_tool_messages_from_agent_result(r)
    assert len(rows) == 1
    assert rows[0]["name"] == "docx_v1_document_rawContent"
    assert rows[0]["content"] == '{"k":1}'


def test_collect_tool_messages_tuple_wrapped_message():
    from langchain_core.messages import ToolMessage

    r = {
        "messages": [
            (ToolMessage("payload", tool_call_id="c1", name="wiki_v1"), {"meta": 1}),
        ],
    }
    rows = collect_tool_messages_from_agent_result(r)
    assert len(rows) == 1
    assert rows[0]["name"] == "wiki_v1"
    assert rows[0]["content"] == "payload"


def test_collect_tool_messages_dict_with_toolmessage_in_data():
    from langchain_core.messages import ToolMessage

    r = {
        "messages": [
            {"type": "tool", "data": ToolMessage("inner", tool_call_id="d1", name="docx")},
        ],
    }
    rows = collect_tool_messages_from_agent_result(r)
    assert len(rows) == 1
    assert rows[0]["content"] == "inner"


def test_collect_tool_messages_langgraph_graphoutput_value():
    from langchain_core.messages import HumanMessage, ToolMessage

    try:
        from langgraph.types import GraphOutput
    except ImportError:
        pytest.skip("langgraph not installed")

    wrapped = GraphOutput(
        value={
            "messages": [
                HumanMessage("hi"),
                ToolMessage("raw-feishu", tool_call_id="x", name="docx_builtin_import"),
            ],
        },
    )
    rows = collect_tool_messages_from_agent_result(wrapped)
    assert len(rows) == 1
    assert rows[0]["name"] == "docx_builtin_import"
    assert rows[0]["content"] == "raw-feishu"


def test_extract_text_from_agent_result_unwraps_graphoutput():
    from langchain_core.messages import AIMessage, HumanMessage

    try:
        from langgraph.types import GraphOutput
    except ImportError:
        pytest.skip("langgraph not installed")

    from app.services.llm_response_extract import extract_text_from_agent_result

    wrapped = GraphOutput(
        value={"messages": [HumanMessage("u"), AIMessage(content="final reply")]},
    )
    assert extract_text_from_agent_result(wrapped) == "final reply"


def test_merge_prepends_mcp_section_and_keeps_original_task() -> None:
    orig = "TASK\n需求：foo"
    brief = "摘录：bar"
    out = merge_mcp_research_into_task_prompt(orig, brief)
    assert brief in out
    assert orig in out
    assert "## MCP 查证摘要" in out
    assert "## 用户任务与输出要求" in out
    assert "文档锚定" in out


def test_merge_empty_brief_inserts_placeholder() -> None:
    orig = "hello"
    out = merge_mcp_research_into_task_prompt(orig, "")
    assert "本次未通过 MCP" in out
    assert "当前未拿到可引用" in out


def test_merge_truncates_long_brief() -> None:
    long_brief = "x" * (_DEFAULT_MCP_BRIEF_MAX_CHARS + 500)
    out = merge_mcp_research_into_task_prompt("body", long_brief)
    assert "取证内容已截断" in out
    assert len(long_brief) > _DEFAULT_MCP_BRIEF_MAX_CHARS
