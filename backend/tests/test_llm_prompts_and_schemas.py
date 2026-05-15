"""§6.2：常量、prompt 拼装、serialize_messages、结构化 Pydantic。"""

import pytest

from app.schemas.llm_output import (
    ChatStructuredOutput,
    GENERATION_SCHEMA_NAME,
    MODULE_GENERATION_SCHEMA_NAME,
    PLAN_SCHEMA_NAME,
    GenerationStructuredOutput,
    PlanStructuredOutput,
)
from app.services import test_case_agent as svc


def test_schema_names_align_ts():
    assert GENERATION_SCHEMA_NAME == "test_case_agent_output"
    assert PLAN_SCHEMA_NAME == "test_case_module_plan"
    assert MODULE_GENERATION_SCHEMA_NAME == "test_case_module_output"


def test_structured_output_guide_has_literal_backslash_n():
    assert "\\n" in svc.STRUCTURED_OUTPUT_GUIDE


def test_serialize_messages_ts_shape():
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "收到"},
    ]
    assert svc.serialize_messages(messages) == "1. user: 你好\n2. assistant: 收到"


def test_build_generate_prompt_ends_with_requirement():
    req = "登录需求"
    prompt = svc.build_generate_test_cases_prompt(req)
    assert prompt.rstrip().endswith(req)
    assert svc.TEST_CASE_GENERATION_GUIDE.strip()[:20] in prompt
    assert "summary/cases" in prompt


def test_build_plan_prompt_contains_coverage():
    p = svc.build_plan_test_case_modules_prompt("极简需求")
    assert svc.COVERAGE_GUIDE[:30] in p
    assert "summary/modules" in p


def test_build_module_prompt_risk_fallback():
    """ASCII titles avoid terminal encoding quirks on Windows runners."""
    mod = {"id": "mod-a", "title": "pay", "description": "payment scope", "riskPoints": []}
    peer = {"id": "mod-b", "title": "order", "description": "order scope", "riskPoints": ["c1"]}
    # 与 TS `input.modules` 一致：一级模块清单含当前模块与同伴模块
    text = svc.build_generate_module_test_cases_prompt("full product", mod, [mod, peer])
    assert "主流程、异常、边界、权限、数据一致性" in text
    assert "1. pay：" in text
    assert "2. order：" in text
    assert 'cases[].category 统一写为“pay”' in text


def test_build_module_prompt_rejects_empty_title():
    with pytest.raises(ValueError, match="module 必须"):
        svc.build_generate_module_test_cases_prompt("r", {"title": ""}, [])


def test_build_chat_prompt_embeds_json_and_history():
    tree = {"data": {"text": "@测试用例"}, "children": []}
    p = svc.build_chat_and_update_mind_map_prompt([{"role": "user", "content": "加一条"}], tree)
    assert '"@测试用例"' in p or "@测试用例" in p
    assert "1. user: 加一条" in p
    assert "当前脑图(JSON)" in p


def test_generation_relaxed_schema_missing_and_int_priority():
    raw = {
        "summary": "",
        "cases": [
            {
                "category": "主流程",
                "topic": "下单",
                "steps": "1. 点购买",
                "expected": "1. 成功",
                "priority": 1,
            },
        ],
    }
    m = GenerationStructuredOutput.model_validate(raw)
    assert m.cases[0].precondition == "默认前置条件"
    assert m.cases[0].id is None
    assert m.cases[0].priority == "P1"
    assert m.summary == "用例生成"


def test_chat_relaxed_priority_int_and_empty_reply():
    raw = {
        "assistantReply": " ",
        "mindMap": {
            "data": {"text": "根", "priority": 2},
            "children": [
                {"data": {"text": "子", "priority": 1}, "children": []},
            ],
        },
    }
    c = ChatStructuredOutput.model_validate(raw)
    assert c.mindMap.data.priority == "P2"
    assert c.mindMap.children[0].data.priority == "P1"
    assert c.assistantReply == "已根据对话更新脑图。"


def test_pydantic_generation_roundtrip():
    raw = {
        "summary": "s",
        "cases": [
            {
                "id": "TC-001",
                "category": "登录",
                "topic": "成功登录",
                "precondition": "已注册",
                "steps": "1. 打开页",
                "expected": "1. 进入首页",
                "priority": "P1",
            }
        ],
    }
    model = GenerationStructuredOutput.model_validate(raw)
    assert model.summary == "s"
    assert model.cases[0].priority == "P1"


def test_pydantic_plan_roundtrip():
    raw = {
        "summary": "p",
        "modules": [
            {"id": "m1", "title": "A", "description": "d", "riskPoints": ["x"]},
        ],
    }
    m = PlanStructuredOutput.model_validate(raw)
    assert m.modules[0].riskPoints == ["x"]


def test_pydantic_chat_recursive_mind_map():
    raw = {
        "assistantReply": "ok",
        "mindMap": {
            "data": {"text": "@测试用例", "uid": "root"},
            "children": [
                {"data": {"text": "@登录", "extraField": 1}, "children": []},
            ],
        },
    }
    c = ChatStructuredOutput.model_validate(raw)
    assert c.assistantReply == "ok"
    assert c.mindMap.children[0].data.text == "@登录"
