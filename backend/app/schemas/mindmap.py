from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MindMapNodeData(BaseModel):
    """脑图节点 data：与 TS `MindMapNode.data` 对齐（priority，非 properties）。"""

    model_config = ConfigDict(extra="allow")

    text: str
    uid: str | None = None
    id: str | None = None
    tag: list[str] | None = None
    priority: Literal["P0", "P1", "P2", "P3"] | None = None


class MindMapNode(BaseModel):
    data: MindMapNodeData
    children: list[MindMapNode] = Field(default_factory=list)


MindMapNode.model_rebuild()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
