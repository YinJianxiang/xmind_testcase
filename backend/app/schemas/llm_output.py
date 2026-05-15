"""
LLM 结构化输出：对齐 next-ai-test-cases `testCaseAgent.ts` 中
`generationSchema` / `planSchema` / `chatSchema`（约 55–85 行）。

供 `ChatOpenAI.with_structured_output(...)` 使用；字段名与 TS / OpenAI JSON Schema 一致。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- generationSchema（放宽：缺字段用默认；priority 接受 int/数字字符串，见校验器）---


def _generation_priority_from_any(v: Any) -> Literal["P0", "P1", "P2", "P3"]:
    if v is None or v == "":
        return "P2"
    if isinstance(v, int):
        if 0 <= v <= 3:
            return f"P{v}"  # type: ignore[return-value]
        return "P2"
    if isinstance(v, str):
        s = v.strip().upper()
        if s in ("P0", "P1", "P2", "P3"):
            return s  # type: ignore[return-value]
        if s.isdigit() and s in ("0", "1", "2", "3"):
            return f"P{s}"  # type: ignore[return-value]
    return "P2"


def _chat_priority_from_any(v: Any) -> Literal["P0", "P1", "P2", "P3"] | None:
    if v is None:
        return None
    if isinstance(v, int):
        if 0 <= v <= 3:
            return f"P{v}"  # type: ignore[return-value]
        return None
    if isinstance(v, str):
        s = v.strip().upper()
        if s in ("P0", "P1", "P2", "P3"):
            return s  # type: ignore[return-value]
        if s.isdigit() and s in ("0", "1", "2", "3"):
            return f"P{s}"  # type: ignore[return-value]
    return None


class GenerationCaseStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    category: str = "功能测试"
    topic: str = "未命名测试"
    precondition: str = "默认前置条件"
    steps: str = "1. 执行待测功能的核心操作"
    expected: str = "1. 系统返回与需求一致的结果"
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"

    @field_validator("category", mode="before")
    @classmethod
    def _category_or_default(cls, v: Any) -> str:
        if v is None:
            return "功能测试"
        s = str(v).strip()
        return s or "功能测试"

    @field_validator("topic", mode="before")
    @classmethod
    def _topic_or_default(cls, v: Any) -> str:
        if v is None:
            return "未命名测试"
        s = str(v).strip()
        return s or "未命名测试"

    @field_validator("precondition", mode="before")
    @classmethod
    def _pre_or_default(cls, v: Any) -> str:
        if v is None:
            return "默认前置条件"
        s = str(v).strip()
        return s or "默认前置条件"

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_or_default(cls, v: Any) -> str:
        if v is None:
            return "1. 执行待测功能的核心操作"
        s = str(v).strip()
        return s or "1. 执行待测功能的核心操作"

    @field_validator("expected", mode="before")
    @classmethod
    def _expected_or_default(cls, v: Any) -> str:
        if v is None:
            return "1. 系统返回与需求一致的结果"
        s = str(v).strip()
        return s or "1. 系统返回与需求一致的结果"

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_from_loose(cls, v: Any) -> str:
        return _generation_priority_from_any(v)


class GenerationStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = "用例生成"
    cases: list[GenerationCaseStructured]

    @field_validator("summary", mode="before")
    @classmethod
    def _summary_or_default(cls, v: Any) -> str:
        if v is None:
            return "用例生成"
        s = str(v).strip()
        return s or "用例生成"


# --- planSchema ---


class PlanModuleStructured(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    riskPoints: list[str]


class PlanStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    modules: list[PlanModuleStructured]


# --- chatSchema（mindMap 递归，data 允许额外键，与 zod passthrough 一致） ---


class MindMapNodeDataParse(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    uid: str | None = None
    id: str | None = None
    tag: list[str] | None = None
    priority: Literal["P0", "P1", "P2", "P3"] | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_loose(cls, v: Any) -> Literal["P0", "P1", "P2", "P3"] | None:
        return _chat_priority_from_any(v)


class ParsedMindMapNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: MindMapNodeDataParse
    children: list[ParsedMindMapNode] = Field(default_factory=list)


ParsedMindMapNode.model_rebuild()


class ChatStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistantReply: str = "已根据对话更新脑图。"
    mindMap: ParsedMindMapNode

    @field_validator("assistantReply", mode="before")
    @classmethod
    def _assistant_non_empty(cls, v: Any) -> str:
        if v is None:
            return "已根据对话更新脑图。"
        t = str(v).strip()
        return t if t else "已根据对话更新脑图。"


# TS schemaName 对照；勿向 OpenAI parse 顶层传 name
GENERATION_SCHEMA_NAME = "test_case_agent_output"
PLAN_SCHEMA_NAME = "test_case_module_plan"
MODULE_GENERATION_SCHEMA_NAME = "test_case_module_output"
CHAT_SCHEMA_NAME = "chat_mind_map_update"


def coerce_plan_llm_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    模型常输出 ``scope`` / ``risk`` 而非 ``description`` / ``riskPoints``；
    在 ``PlanStructuredOutput.model_validate`` 之前调用，收束为 planSchema 形态。
    """
    out = dict(data)
    raw_modules = out.get("modules")
    if not isinstance(raw_modules, list):
        return out

    fixed: list[dict[str, Any]] = []
    for m in raw_modules:
        if not isinstance(m, dict):
            continue
        x = dict(m)

        desc = str(x.get("description") or x.get("scope") or x.get("testingScope") or "").strip()
        title_fallback = str(x.get("title") or "").strip()
        if not desc:
            desc = f"{title_fallback}相关测试范围" if title_fallback else "（未提供描述）"

        rp_any = x.get("riskPoints") or x.get("risk_points")
        if isinstance(rp_any, str) and rp_any.strip():
            rp = [p.strip() for p in re.split(r"[、,，;\n；;|｜/]", rp_any) if p.strip()]
            if not rp:
                rp = [rp_any.strip()]
        elif isinstance(rp_any, list):
            rp = [str(i).strip() for i in rp_any if str(i).strip()]
        else:
            raw_r = x.get("risk") or x.get("risks")
            if isinstance(raw_r, str) and raw_r.strip():
                rp = [p.strip() for p in re.split(r"[、,，;\n；;|｜/]", raw_r) if p.strip()]
                if not rp:
                    rp = [raw_r.strip()]
            elif isinstance(raw_r, list):
                rp = [str(i).strip() for i in raw_r if str(i).strip()]
            else:
                rp = ["主流程", "异常", "边界", "权限", "数据一致性"]

        mid = str(x.get("id") or "").strip() or "module"
        ttl = str(x.get("title") or "").strip() or "未命名模块"

        fixed.append(
            {
                "id": mid,
                "title": ttl,
                "description": desc,
                "riskPoints": rp,
            }
        )

    out["modules"] = fixed
    out["summary"] = str(out.get("summary") or "").strip() or "模块规划"
    return out
