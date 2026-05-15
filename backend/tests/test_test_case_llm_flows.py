"""`test_case_llm`：mock LLM，不请求真实 API。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.llm_output import (
    GenerationCaseStructured,
    GenerationStructuredOutput,
    PlanModuleStructured,
    PlanStructuredOutput,
)
from app.services import test_case_llm as svc


def test_plan_test_case_modules_pipeline():
    async def _run() -> None:
        fake = PlanStructuredOutput(
            summary="概览",
            modules=[
                PlanModuleStructured(id="m1", title="登录", description="登录域", riskPoints=["权限"]),
            ],
        )
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value=fake)
        llm = MagicMock()
        llm.with_structured_output.return_value = runnable

        out = await svc.plan_test_case_modules("用户需求", llm=llm)

        assert out["summary"] == "概览"
        assert len(out["modules"]) >= 1
        assert out["modules"][0]["title"] == "登录"
        assert out["mindMap"]["data"]["text"] == "@测试用例"
        assert out["mindMap"]["children"][0]["data"]["text"] == "@登录"

    asyncio.run(_run())


def test_generate_test_cases_pipeline():
    async def _run() -> None:
        fake = GenerationStructuredOutput(
            summary="s",
            cases=[
                GenerationCaseStructured(
                    id="TC-001",
                    category="功能测试",
                    topic="用例A",
                    precondition="默认前置条件",
                    steps="1. 操作",
                    expected="1. 成功",
                    priority="P1",
                ),
            ],
        )
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value=fake)
        llm = MagicMock()
        llm.with_structured_output.return_value = runnable

        out = await svc.generate_test_cases("简单需求", llm=llm)

        assert out["summary"] == "s"
        assert len(out["cases"]) == 1
        assert out["cases"][0]["topic"] == "用例A"
        assert out["mindMap"]["children"]

    asyncio.run(_run())


def test_generate_module_test_cases_with_mcp_prefetch_kwarg():
    """传入 mcp_document_brief 时应交给 invoke_structured_with_mcp(prefetched_research=...)。"""
    async def _run() -> None:
        fake = GenerationStructuredOutput(
            summary="ms",
            cases=[
                GenerationCaseStructured(
                    id="x",
                    category="支付",
                    topic="t",
                    precondition="p",
                    steps="1. s",
                    expected="1. e",
                    priority="P2",
                ),
            ],
        )
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value=fake)
        llm = MagicMock()
        llm.with_structured_output.return_value = runnable

        mod = {"id": "pay", "title": "支付", "description": "支付模块", "riskPoints": []}
        peers = [mod]

        with patch(
            "app.services.test_case_llm.invoke_structured_with_mcp",
            new_callable=AsyncMock,
        ) as mcp_invoke:
            mcp_invoke.return_value = (fake, None)
            out = await svc.generate_module_test_cases(
                "全局",
                mod,
                peers,
                llm=llm,
                mcp_document_brief="  wiki正文摘录 ",
            )
            mcp_invoke.assert_awaited_once()
            assert mcp_invoke.await_args.kwargs["prefetched_research"] == "wiki正文摘录"
            assert out["module"]["title"] == "支付"

    asyncio.run(_run())


def test_generate_module_test_cases_pipeline():
    async def _run() -> None:
        fake = GenerationStructuredOutput(
            summary="ms",
            cases=[
                GenerationCaseStructured(
                    id="x",
                    category="支付",
                    topic="t",
                    precondition="p",
                    steps="1. s",
                    expected="1. e",
                    priority="P2",
                ),
            ],
        )
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value=fake)
        llm = MagicMock()
        llm.with_structured_output.return_value = runnable

        mod = {"id": "pay", "title": "支付", "description": "支付模块", "riskPoints": []}
        peers = [mod]

        out = await svc.generate_module_test_cases("全局", mod, peers, llm=llm)

        assert out["summary"] == "ms"
        assert out["module"]["title"] == "支付"
        assert out["cases"][0]["id"].startswith("pay-TC-")
        assert out["mindMap"]["data"]["text"] == "@支付"

    asyncio.run(_run())


def test_chat_and_update_mind_map_pipeline():
    async def _run() -> None:
        mind_json = (
            '{"assistantReply":"已添加","mindMap":'
            '{"data":{"text":"@测试用例","uid":"root","id":"root"},"children":[]}}'
        )

        class R:
            content = mind_json

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=R())

        out = await svc.chat_and_update_mind_map(
            [{"role": "user", "content": "加一个用例"}],
            {"data": {"text": "x"}},
            llm=llm,
        )

        assert out["assistantReply"] == "已添加"
        assert out["mindMap"]["data"]["text"] == "@测试用例"

    asyncio.run(_run())
