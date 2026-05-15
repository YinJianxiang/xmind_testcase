"""纯函数单元测试：`app/services/test_case_agent.py`（不测 LLM、不测 HTTP）。"""

from __future__ import annotations

import pytest

from app.services.test_case_agent import (
    PRECONDITION_TAG,
    build_expected_line,
    build_mind_map_from_cases,
    build_module_mind_map_from_cases,
    build_skeleton_mind_map,
    extract_priority_prefix,
    normalize_cases,
    normalize_module_cases,
    normalize_module_id,
    normalize_modules,
    normalize_numbered_lines,
    normalize_parsed_mind_map,
    normalize_priority,
    normalize_priority_tag,
    split_numbered_lines,
    strip_precondition_prefix,
    strip_priority_prefix,
)


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("p0", "P0"),
        ("P1 ", "P1"),
        ("xx", "P2"),
        ("", "P2"),
    ],
)
def test_normalize_priority(raw: str, expect: str) -> None:
    assert normalize_priority(raw) == expect


@pytest.mark.parametrize(
    "text,expect",
    [
        ("  [p1] 登录  ", "登录"),
        ("P2：注册", "注册"),
        ("无前缀", "无前缀"),
    ],
)
def test_strip_priority_prefix(text: str, expect: str) -> None:
    assert strip_priority_prefix(text) == expect


@pytest.mark.parametrize(
    "text,expect",
    [
        ("! 已登录 ", "已登录"),
        ("无叹号", "无叹号"),
    ],
)
def test_strip_precondition_prefix(text: str, expect: str) -> None:
    assert strip_precondition_prefix(text) == expect


def test_normalize_numbered_lines_empty_uses_fallback() -> None:
    out = normalize_numbered_lines("", "占位")
    assert out == "1. 占位"


def test_normalize_numbered_lines_keeps_existing_numbers() -> None:
    raw = "1. A\nB"
    out = normalize_numbered_lines(raw, "x")
    lines = out.split("\n")
    assert lines[0] == "1. A"
    assert lines[1].startswith("2.")


def test_split_numbered_lines() -> None:
    assert split_numbered_lines("1. a\n\n2. b") == ["1. a", "2. b"]


def test_normalize_cases_dedupe_by_key() -> None:
    cases = [
        {
            "id": "",
            "category": "@登录",
            "topic": "发短信",
            "precondition": "x",
            "steps": "点",
            "expected": "ok",
            "priority": "p1",
        },
        {
            "id": "",
            "category": "登录",
            "topic": "[P1] 发短信",
            "precondition": "x",
            "steps": "重复",
            "expected": "重复",
            "priority": "P1",
        },
    ]
    out = normalize_cases(cases)
    assert len(out) == 1
    assert out[0]["priority"] == "P1"
    assert out[0]["category"] == "登录"


def test_normalize_module_id_slug() -> None:
    assert normalize_module_id("  Login V2?!  ", 0) == "login-v2"


def test_normalize_modules_empty_fallback() -> None:
    out = normalize_modules([])
    assert len(out) == 1
    assert out[0]["id"] == "module-01"


def test_build_expected_line() -> None:
    assert build_expected_line(0, []) == "期望结果 1"
    assert build_expected_line(1, ["a", "b"]) == "b"


def test_build_skeleton_mind_map() -> None:
    mods = normalize_modules([{"title": "支付", "id": "", "description": "", "riskPoints": []}])
    tree = build_skeleton_mind_map(mods)
    assert tree["data"]["text"] == "@测试用例"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["data"]["text"] == "@支付"


def test_build_mind_map_precondition_has_tag() -> None:
    cases = normalize_cases(
        [
            {
                "id": "TC-001",
                "category": "登录",
                "topic": "发短信",
                "precondition": "已注册",
                "steps": "点发送",
                "expected": "成功",
                "priority": "P1",
            }
        ]
    )
    tree = build_mind_map_from_cases(list(cases))
    pre_node = tree["children"][0]["children"][0]
    assert PRECONDITION_TAG in pre_node["data"].get("tag", [])


def test_normalize_module_cases_ids() -> None:
    module = normalize_modules([{"title": "A", "id": "mod-a", "description": "", "riskPoints": []}])[0]
    rows = normalize_module_cases(
        module,
        [
            {
                "id": "",
                "category": "错",
                "topic": "t1",
                "precondition": "p",
                "steps": "s",
                "expected": "e",
                "priority": "P0",
            },
        ],
    )
    assert rows[0]["id"] == "mod-a-TC-001"
    assert rows[0]["category"] == "A"


def test_build_module_subtree_matches_root_children_shape() -> None:
    module = normalize_modules([{"title": "M", "id": "mid", "description": "", "riskPoints": []}])[0]
    cases = normalize_module_cases(
        module,
        [
            {
                "id": "",
                "category": "x",
                "topic": "u",
                "precondition": "! pre",
                "steps": "",
                "expected": "",
                "priority": "P2",
            },
        ],
    )
    subtree = build_module_mind_map_from_cases(module, cases)
    assert subtree["data"]["uid"] == "mid"
    assert subtree["children"][0]["data"].get("tag") == [PRECONDITION_TAG]


def test_normalize_parsed_mind_map_rewrites_tags() -> None:
    raw = {
        "data": {
            "text": "[p1] 用例标题",
            "children": [],  # no-op passthrough checks only data path
            "tag": None,
            "priority": None,
        },
        "children": [],
    }
    # Parsed shape: only data.children was wrong above - fix structure for real call
    node = {"data": {"text": "[p1] 用例标题"}, "children": []}
    fixed = normalize_parsed_mind_map(node)
    assert fixed["data"]["priority"] == "P1"
    assert "P1" in fixed["data"].get("tag", [])
    assert fixed["data"]["text"] == "用例标题"


@pytest.fixture
def sample_plan_snapshot() -> dict:
    """可把浏览器 Network 里 `/api/test-case-agent/plan` 的响应粘进来做黄金对比。"""
    return {
        "summary": "...",
        "modules": [{"id": "m1", "title": "核心", "description": "d", "riskPoints": []}],
        "mindMap": {},  # 省略或由 build_skeletonMindMap(normalize_modules(...)) 生成
    }


def test_golden_plan_shape(sample_plan_snapshot: dict) -> None:
    mods = normalize_modules(sample_plan_snapshot["modules"])
    sk = build_skeleton_mind_map(mods)
    assert sk["children"][0]["data"]["uid"] == "m1"
