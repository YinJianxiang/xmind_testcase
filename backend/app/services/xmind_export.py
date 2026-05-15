"""
XMind `.xmind` ZIP 导出：对齐 `src/app/api/test-case-agent/export-xmind/route.ts`。
"""

from __future__ import annotations

import json
import re
import secrets
import zipfile
from io import BytesIO
from typing import Any


def uid() -> str:
    """16 位十六进制，与 TS `randomUUID` 去横线后 `slice(0, 16)` 同形。"""
    return secrets.token_hex(8)


def strip_precondition_prefix(text: str) -> str:
    return re.sub(r"^\s*!\s*", "", text).strip()


def parse_priority_from_text(text: str) -> tuple[str, str | None]:
    raw = (text or "").strip()
    m = re.match(r"^\[?\s*(P[0-3])\s*\]?\s*[-:：]?\s*(.*)$", raw, flags=re.I)
    if not m:
        return strip_precondition_prefix(raw), None
    pr = m.group(1).upper()
    clean = strip_precondition_prefix((m.group(2) or "").strip()) or raw
    return clean, pr  # type: ignore[return-value]


def to_priority_marker(priority: str) -> str:
    m = {
        "P0": "priority-1",
        "P1": "priority-2",
        "P2": "priority-3",
        "P3": "priority-4",
    }[priority]
    return m


def split_numbered_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def build_expected_line(step_index: int, expected_lines: list[str]) -> str:
    if step_index < len(expected_lines) and expected_lines[step_index]:
        return expected_lines[step_index]
    if expected_lines:
        return expected_lines[0]
    return f"期望结果 {step_index + 1}"


def to_xmind_topic(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") or {}
    text_raw = str(data.get("text") or "")
    clean_title, from_text = parse_priority_from_text(text_raw)
    priority = data.get("priority") or from_text

    topic: dict[str, Any] = {
        "id": uid(),
        "title": clean_title or "未命名节点",
    }
    if priority:
        mid = to_priority_marker(str(priority))
        topic["markers"] = [{"markerId": mid}]
        topic["markerRefs"] = [mid]

    children = node.get("children") or []
    if isinstance(children, list) and children:
        topic["children"] = {"attached": [to_xmind_topic(ch) for ch in children if isinstance(ch, dict)]}

    return topic


def build_root_from_cases(test_cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in test_cases:
        cat = (str(item.get("category") or "").strip() or "功能测试")
        pre = (str(item.get("precondition") or "").strip() or "默认前置条件")
        grouped.setdefault(cat, {}).setdefault(pre, []).append(item)

    category_topics: list[dict[str, Any]] = []
    for category, pre_map in grouped.items():
        pre_topics: list[dict[str, Any]] = []
        for precondition, items in pre_map.items():
            case_children: list[dict[str, Any]] = []
            for it in items:
                step_lines = split_numbered_lines(str(it.get("steps") or ""))
                expected_lines = split_numbered_lines(str(it.get("expected") or ""))
                safe_steps = step_lines if step_lines else ["1. 未提供测试步骤"]
                if expected_lines:
                    exp_join = "\n".join(expected_lines)
                else:
                    exp_join = "\n".join(
                        build_expected_line(i, expected_lines) for i in range(len(safe_steps))
                    )
                pr = str(it.get("priority") or "P2")
                mid = to_priority_marker(pr)
                tid = str(it.get("id") or "").strip() or uid()
                title_topic = str(it.get("topic") or "").strip() or "未命名测试"

                case_children.append(
                    {
                        "id": tid,
                        "title": title_topic,
                        "priority": pr,
                        "precondition": str(it.get("precondition") or ""),
                        "steps": str(it.get("steps") or ""),
                        "expected": str(it.get("expected") or ""),
                        "markers": [{"markerId": mid}],
                        "markerRefs": [mid],
                        "children": {
                            "attached": [
                                {
                                    "id": uid(),
                                    "title": "测试步骤\n" + "\n".join(safe_steps),
                                    "children": {
                                        "attached": [
                                            {"id": uid(), "title": "期望结果\n" + exp_join},
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                )

            pre_topics.append(
                {
                    "id": uid(),
                    "title": strip_precondition_prefix(precondition) or "默认前置条件",
                    "children": {"attached": case_children},
                }
            )

        category_topics.append(
            {
                "id": uid(),
                "title": f"@{category}",
                "children": {"attached": pre_topics},
            }
        )

    return {
        "id": "root",
        "title": "@测试用例",
        "root": True,
        "children": {"attached": category_topics},
    }


def build_xmind_zip(
    mind_map: dict[str, Any],
    test_cases: list[dict[str, Any]] | None,
    title: str | None,
) -> bytes:
    """
    返回 `.xmind`（ZIP）二进制，内含 `content.json` 与 `metadata.json`。
    """
    data_root = mind_map.get("data") or {}
    sheet_title = (title or "").strip() or str(data_root.get("text") or "测试用例")

    if test_cases:
        root_topic = build_root_from_cases(test_cases)
    else:
        root_topic = to_xmind_topic(mind_map)

    content: list[dict[str, Any]] = [
        {
            "id": uid(),
            "class": "sheet",
            "title": sheet_title,
            "rootTopic": root_topic,
        }
    ]

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        zf.writestr(
            "metadata.json",
            json.dumps({"creator": {"name": "next-ai-test-cases"}}, ensure_ascii=False, indent=2),
        )
    return buf.getvalue()


def content_disposition_filename(sheet_title: str) -> str:
    """与 TS `encodeURIComponent(sheetTitle).xmind` 对齐（ASCII/中文均 percent-encode）。"""
    from urllib.parse import quote

    safe = quote(sheet_title, safe="")
    return f'attachment; filename="{safe}.xmind"'
