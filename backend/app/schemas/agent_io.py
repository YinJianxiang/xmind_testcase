"""API 契约：对照 next-ai-test-cases Route + types；JSON 驼峰字段用 Field(alias)。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.mindmap import ChatMessage, MindMapNode


# --- Module & case ---


class ModulePlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    description: str
    risk_points: list[str] = Field(alias="riskPoints")


class TestCaseItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    category: str
    topic: str
    precondition: str
    steps: str
    expected: str
    priority: Literal["P0", "P1", "P2", "P3"]


# --- Plan ---


class PlanRequest(BaseModel):
    requirement: str


class PlanResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    modules: list[ModulePlan]
    mind_map: MindMapNode = Field(alias="mindMap")
    mcp_document_brief: str | None = Field(default=None, alias="mcpDocumentBrief")


class PlanRequirementSourceRequest(BaseModel):
    requirement: str


class McpDocumentToolRawEntry(BaseModel):
    """MCP 工具单次调用的原始返回（如飞书文档接口 JSON/正文），用于与 ``mcpDocumentBrief`` 对照。"""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    name: str | None = None
    tool_call_id: str | None = Field(default=None, alias="toolCallId")
    content: Any = None


class PlanRequirementSourceResponse(BaseModel):
    """``POST /plan/requirement-source``：对齐 MCP Phase1-only。"""

    model_config = ConfigDict(populate_by_name=True)

    mcp_document_brief: str = Field(default="", alias="mcpDocumentBrief")
    mcp_document_tool_raw: list[McpDocumentToolRawEntry] | None = Field(
        default=None,
        alias="mcpDocumentToolRaw",
    )


class PlanModulesOnlyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement: str
    mcp_document_brief: str | None = Field(default=None, alias="mcpDocumentBrief")


class PlanModulesOnlyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    modules: list[ModulePlan]


class PlanSkeletonRequest(BaseModel):
    modules: list[ModulePlan]


class PlanSkeletonResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mind_map: MindMapNode = Field(alias="mindMap")


# --- Module ---


class ModuleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement: str
    module: ModulePlan
    modules: list[ModulePlan]
    #: 与 ``POST /plan`` 返回的 ``mcpDocumentBrief`` 一致时，本请求跳过 MCP phase1，仅合并摘要后结构化生成。
    mcp_document_brief: str | None = Field(default=None, alias="mcpDocumentBrief")


class ModuleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    module: ModulePlan
    cases: list[TestCaseItem]
    mind_map: MindMapNode = Field(alias="mindMap")


# --- Chat ---


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    messages: list[ChatMessage]
    current_mind_map: MindMapNode = Field(alias="currentMindMap")


class ChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assistant_reply: str = Field(alias="assistantReply")
    mind_map: MindMapNode = Field(alias="mindMap")


# --- Legacy 一次生成 ---


class GenerateRequest(BaseModel):
    requirement: str


class GenerateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    cases: list[TestCaseItem]
    mind_map: MindMapNode = Field(alias="mindMap")


# --- Export XMind ---


class ExportXmindRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mind_map: MindMapNode = Field(alias="mindMap")
    test_cases: list[TestCaseItem] | None = Field(default=None, alias="testCases")
    title: str | None = None
