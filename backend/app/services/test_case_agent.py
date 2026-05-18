"""
纯函数与脑图构建：对齐 next-ai-test-cases `src/lib/agent/testCaseAgent.ts`（约 38–418 行）。
含与 TS 字面一致的模型提示常量、`build_*_prompt` / `serialize_messages`。
不含 LLM / 路由；节点为与 JSON 同形的 dict。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

Priority = Literal["P0", "P1", "P2", "P3"]

PRECONDITION_TAG = "前置"

# --- `TEST_CASE_*` 常量与 TS `testCaseAgent.ts` 87–111 行字面一致 ---

TEST_CASE_GENERATION_GUIDE = """生成测试用例时必须遵守：
1. 先在内部识别一级功能模块骨架，再逐个模块补充完整场景，最后做一次质量审查；最终只输出完整 JSON。
2. 覆盖必须按模块组织，避免把所有用例堆到“功能测试”一个分类中；类别要能帮助阅读者快速定位风险。
3. 每个用例都必须可执行：前置条件、步骤、期望结果不能为空，步骤和期望结果必须按编号一一对应。
4. 不输出重复用例；同一风险点如果需要多数据覆盖，应体现在步骤或标题中，而不是复制相同用例。
5. 优先级必须体现风险：P0 只给主链路、数据安全、资金、权限、核心可用性；P1 给高频分支和关键异常；P2/P3 给低频、兼容或体验项。
6. 若上文含有效的「MCP 查证摘要」（文档摘录而非仅提示拉取失败），用例必须与摘要中的规则、流程、术语一致，**禁止**为凑数量编造摘要未提及的需求；仅摘要与用户任务均未覆盖的细节可做最小假设并在 summary 写明。若无有效文档摘录，信息不足时可做最小必要合理假设并继续在 summary 说明。"""

COVERAGE_GUIDE = """覆盖维度（必须尽量覆盖）：
1. 主流程/冒烟：核心成功路径、关键端到端流程。
2. 分支流程：不同角色、不同入口、不同状态流转。
3. 边界值：长度、范围、阈值、次数、时间窗口、分页临界点。
4. 异常与失败：超时、网络抖动、第三方失败、参数非法、幂等重试、降级兜底。
5. 权限与安全：鉴权、越权、未登录、会话过期、数据隔离、输入安全校验。
6. 数据一致性：前后端一致、缓存一致、并发冲突、重复提交、事务回滚。
7. 易用性与兼容性：错误提示可理解、关键兼容场景（Web/移动端或主流浏览器）。"""

STRUCTURED_OUTPUT_GUIDE = """输出规范：
1. 字段固定为：summary/cases。
2. cases[].category 必须使用测试类别名，不带 @ 前缀。
3. cases[].topic 为测试用例名称，不包含类别名。
4. cases[].steps 使用单个字符串，步骤之间用换行符 \\n 分隔，格式如：1. 打开页面。
5. cases[].expected 使用单个字符串，并与 steps 同编号逐条对应。
6. 系统会根据 cases 自动构建脑图，因此不要额外输出 mindMap 或其他字段。
7. 最终只输出结构化 JSON，不要包含 markdown、解释或额外文本。"""


class MindMapNodeData(TypedDict, total=False):
    text: str
    uid: str
    id: str
    tag: list[str]
    priority: Priority


class TestCaseModulePlan(TypedDict, total=False):
    id: str
    title: str
    description: str
    riskPoints: list[str]


class TestCaseCaseItem(TypedDict, total=False):
    id: str
    category: str
    topic: str
    precondition: str
    steps: str
    expected: str
    priority: str


def normalize_priority(value: str) -> Priority:
    priority = value.strip().upper()
    if priority in ("P0", "P1", "P2", "P3"):
        return priority  # type: ignore[return-value]
    return "P2"


def strip_priority_prefix(text: str) -> str:
    return re.sub(r"^\s*\[?P[0-3]\]?\s*[-:：]?\s*", "", text, flags=re.I).strip()


def strip_precondition_prefix(text: str) -> str:
    return re.sub(r"^\s*!\s*", "", text).strip()


def extract_priority_prefix(text: str) -> Priority | None:
    m = re.match(r"^\s*\[?\s*(P[0-3])\s*\]?\s*[-:：]?", text, flags=re.I)
    if not m:
        return None
    return m.group(1).upper()  # type: ignore[return-value]


def normalize_priority_tag(value: object) -> Priority | None:
    if isinstance(value, str) and re.fullmatch(r"P[0-3]", value.strip(), flags=re.I):
        return value.strip().upper()  # type: ignore[return-value]
    return None


def normalize_numbered_lines(value: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (value or "").split("\n") if ln.strip()]
    safe_lines = lines if lines else [fallback]

    def add_prefix(line: str, index: int) -> str:
        if re.match(r"^\d+\s*[\.\、:：)]", line):
            return line
        return f"{index + 1}. {line}"

    return "\n".join(add_prefix(line, i) for i, line in enumerate(safe_lines))


def split_numbered_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def normalize_cases(cases: list[TestCaseCaseItem] | None) -> list[TestCaseCaseItem]:
    seen: set[str] = set()
    normalized: list[TestCaseCaseItem] = []

    for item in cases or []:
        raw_category = (item.get("category") or "功能测试").strip()
        category = re.sub(r"^@", "", raw_category).strip() or "功能测试"
        precondition = strip_precondition_prefix(item.get("precondition") or "默认前置条件") or "默认前置条件"
        topic = strip_priority_prefix(item.get("topic") or "未命名测试") or "未命名测试"
        key = f"{category}|{precondition}|{topic}".lower()

        if key in seen:
            continue
        seen.add(key)

        steps = normalize_numbered_lines(item.get("steps") or "", "执行待测功能的核心操作")
        expected = normalize_numbered_lines(item.get("expected") or "", "系统返回与需求一致的结果")
        pr = normalize_priority(str(item.get("priority") or "P2"))

        tid = (item.get("id") or "").strip() or f"TC-{str(len(normalized) + 1).zfill(3)}"

        normalized.append(
            {
                **item,
                "id": tid,
                "category": category,
                "precondition": precondition,
                "topic": topic,
                "steps": steps,
                "expected": expected,
                "priority": pr,
            }
        )

    return normalized


def normalize_module_id(value: str, index: int) -> str:
    cid = value.strip().lower()
    cid = re.sub(r"[^a-z0-9_-]+", "-", cid)
    cid = re.sub(r"^-+|-+$", "", cid)
    return cid or f"module-{str(index + 1).zfill(2)}"


def normalize_modules(modules: list[TestCaseModulePlan] | None) -> list[TestCaseModulePlan]:
    seen: set[str] = set()
    normalized: list[TestCaseModulePlan] = []

    for item in modules or []:
        title = re.sub(r"^@", "", (item.get("title") or "").strip()).strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)

        risks = item.get("riskPoints") or []
        if not isinstance(risks, list):
            risks = []
        risk_points = [str(r).strip() for r in risks if str(r).strip()]

        normalized.append(
            {
                "id": normalize_module_id(item.get("id") or title, len(normalized)),
                "title": title,
                "description": (item.get("description") or f"{title}相关测试范围").strip(),
                "riskPoints": risk_points,
            }
        )

    if normalized:
        return normalized

    return [
        {
            "id": "module-01",
            "title": "核心流程",
            "description": "需求核心流程与关键异常覆盖",
            "riskPoints": ["主流程正确性", "关键异常处理", "数据一致性"],
        }
    ]


def normalize_module_cases(module: TestCaseModulePlan, cases: list[TestCaseCaseItem] | None) -> list[TestCaseCaseItem]:
    out: list[TestCaseCaseItem] = []
    for index, item in enumerate(normalize_cases(cases)):
        mid = module.get("id") or "module"
        out.append(
            {
                **item,
                "id": f"{mid}-TC-{str(index + 1).zfill(3)}",
                "category": module.get("title") or "",
                "topic": strip_priority_prefix(item.get("topic") or "") or (item.get("topic") or ""),
            }
        )
    return out


def build_expected_line(step_index: int, expected_lines: list[str]) -> str:
    if step_index < len(expected_lines) and expected_lines[step_index]:
        return expected_lines[step_index]
    if expected_lines:
        return expected_lines[0]
    return f"期望结果 {step_index + 1}"


def build_mind_map_from_cases(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for c in cases:
        category = (c.get("category") or "功能测试").strip()
        precondition = strip_precondition_prefix(c.get("precondition") or "默认前置条件") or "默认前置条件"
        topic = (c.get("topic") or "未命名测试").strip()
        if category not in grouped:
            grouped[category] = {}
        pre_map = grouped[category]
        if precondition not in pre_map:
            pre_map[precondition] = []
        pre_map[precondition].append(
            {
                "id": c.get("id"),
                "topic": topic,
                "priority": c.get("priority"),
                "steps": (c.get("steps") or "").strip(),
                "expected": (c.get("expected") or "").strip(),
            }
        )

    def step_expected_children(it: dict[str, Any]) -> list[dict[str, Any]]:
        step_lines = split_numbered_lines(it["steps"])
        expected_lines = split_numbered_lines(it["expected"])
        safe_steps = step_lines if step_lines else ["1. 未提供测试步骤"]
        if expected_lines:
            safe_expected = expected_lines
        else:
            safe_expected = [build_expected_line(idx, expected_lines) for idx in range(len(safe_steps))]

        step_blob = "\n".join(safe_steps)
        exp_blob = "\n".join(safe_expected)

        return [
            {
                "data": {"text": f"测试步骤\n{step_blob}"},
                "children": [
                    {
                        "data": {"text": f"期望结果\n{exp_blob}"},
                        "children": [],
                    }
                ],
            }
        ]

    children: list[dict[str, Any]] = []
    for category, pre_map in grouped.items():
        cat_clean = re.sub(r"^@", "", category)
        cat_children: list[dict[str, Any]] = []
        for precondition, items in pre_map.items():
            cat_children.append(
                {
                    "data": {"text": strip_precondition_prefix(precondition), "tag": [PRECONDITION_TAG]},
                    "children": [
                        {
                            "data": {
                                "text": strip_priority_prefix(it["topic"]) or "未命名测试",
                                "priority": it["priority"],
                                "tag": [it["priority"]],
                                "id": it["id"],
                                "uid": it["id"],
                            },
                            "children": step_expected_children(it),
                        }
                        for it in items
                    ],
                }
            )
        children.append({"data": {"text": f"@{cat_clean}"}, "children": cat_children})

    return {"data": {"text": "@测试用例", "uid": "root", "id": "root"}, "children": children}


def build_skeleton_mind_map(modules: list[TestCaseModulePlan]) -> dict[str, Any]:
    return {
        "data": {"text": "@测试用例", "uid": "root", "id": "root"},
        "children": [
            {
                "data": {
                    "text": f"@{m.get('title', '')}",
                    "uid": m.get("id"),
                    "id": m.get("id"),
                },
                "children": [],
            }
            for m in modules
        ],
    }


def build_module_mind_map_from_cases(module: TestCaseModulePlan, cases: list[TestCaseCaseItem] | None) -> dict[str, Any]:
    grouped: dict[str, list[TestCaseCaseItem]] = {}
    for c in cases or []:
        precondition = strip_precondition_prefix(c.get("precondition") or "默认前置条件") or "默认前置条件"
        grouped.setdefault(precondition, []).append(c)

    def item_children(it: TestCaseCaseItem) -> list[dict[str, Any]]:
        step_lines = split_numbered_lines(it.get("steps") or "")
        expected_lines = split_numbered_lines(it.get("expected") or "")
        safe_steps = step_lines if step_lines else ["1. 未提供测试步骤"]
        if expected_lines:
            safe_expected = expected_lines
        else:
            safe_expected = [build_expected_line(idx, expected_lines) for idx in range(len(safe_steps))]

        step_blob = "\n".join(safe_steps)
        exp_blob = "\n".join(safe_expected)

        return [
            {
                "data": {"text": f"测试步骤\n{step_blob}"},
                "children": [
                    {
                        "data": {"text": f"期望结果\n{exp_blob}"},
                        "children": [],
                    }
                ],
            }
        ]

    mid = module.get("id") or "module"
    children: list[dict[str, Any]] = []
    for pre_index, (precondition, items) in enumerate(grouped.items()):
        pre_id = f"{mid}-pre-{str(pre_index + 1).zfill(2)}"
        children.append(
            {
                "data": {
                    "text": strip_precondition_prefix(precondition),
                    "uid": pre_id,
                    "id": pre_id,
                    "tag": [PRECONDITION_TAG],
                },
                "children": [
                    {
                        "data": {
                            "text": strip_priority_prefix(it.get("topic") or "") or "未命名测试",
                            "priority": it.get("priority"),
                            "tag": [it.get("priority")],
                            "id": it.get("id"),
                            "uid": it.get("id"),
                        },
                        "children": item_children(it),
                    }
                    for it in items
                ],
            }
        )

    return {
        "data": {"text": f"@{module.get('title', '')}", "uid": mid, "id": mid},
        "children": children,
    }


def normalize_parsed_mind_map(node: dict[str, Any]) -> dict[str, Any]:
    data = dict(node.get("data") or {})
    text_raw = str(data.get("text") or "")

    raw_tags = data.get("tag")
    tags = [str(t) for t in (raw_tags or []) if t is not None and str(t)]

    prio_from_field = normalize_priority_tag(data.get("priority"))
    prio_from_tags = None
    for tag in tags:
        prio_from_tags = normalize_priority_tag(tag)
        if prio_from_tags:
            break

    priority: Priority | None = prio_from_field or prio_from_tags or extract_priority_prefix(text_raw)

    if priority:
        text_after_prio = strip_priority_prefix(text_raw) or text_raw
    else:
        text_after_prio = text_raw

    has_pre_tag = PRECONDITION_TAG in tags or text_after_prio.strip().startswith("!")
    clean_text = strip_precondition_prefix(text_after_prio) or text_after_prio

    business_tags = [t for t in tags if not normalize_priority_tag(t) and t != PRECONDITION_TAG]
    next_tags: list[str] = []
    if priority:
        next_tags.append(priority)
    if has_pre_tag:
        next_tags.append(PRECONDITION_TAG)
    next_tags.extend(business_tags)

    out_data: MindMapNodeData = {"text": clean_text}
    if data.get("uid"):
        out_data["uid"] = str(data["uid"])
    if data.get("id"):
        out_data["id"] = str(data["id"])
    if priority:
        out_data["priority"] = priority
    if next_tags:
        out_data["tag"] = next_tags

    raw_children = node.get("children") or []
    child_list = raw_children if isinstance(raw_children, list) else []

    return {
        "data": out_data,
        "children": [normalize_parsed_mind_map(ch) for ch in child_list if isinstance(ch, dict)],
    }


def serialize_messages(messages: Sequence[Any]) -> str:
    """对齐 TS `serializeMessages`（约 759–761）：`1. role: content` 逐条拼接。"""
    lines: list[str] = []
    for index, raw in enumerate(messages):
        role: str
        content: str
        if isinstance(raw, Mapping):
            role = str(raw.get("role", ""))
            content = str(raw.get("content", ""))
        else:
            role = str(getattr(raw, "role", ""))
            content = str(getattr(raw, "content", ""))
        lines.append(f"{index + 1}. {role}: {content}")
    return "\n".join(lines)


def build_generate_test_cases_prompt(requirement: str) -> str:
    """对齐 `generateTestCases` 中拼接的 prompt（TS 约 639–666）。"""
    return f"""你是资深测试架构师。请根据输入需求生成“数量充足、覆盖全面、可执行”的测试用例。

总体目标：
- 在不重复的前提下，尽量多产出高价值用例。
- 若上文有 MCP 查证摘要：条数仍须满足下限，但每一条都应能关联到摘要或用户任务中的具体需求点，禁写与文档无关的泛化用例。
- 默认至少生成 30 条用例；如果需求非常小，至少生成 20 条；如果需求复杂，可超过 40 条。

{TEST_CASE_GENERATION_GUIDE}

{COVERAGE_GUIDE}

优先级要求：
- P0：主链路、资金/数据安全、核心可用性风险。
- P1：高频分支和重要异常。
- P2/P3：低频或体验优化项。
- 输出中必须同时包含 P0/P1/P2（如适用可含 P3）。

{STRUCTURED_OUTPUT_GUIDE}

质量审查：
- 输出前自查是否遗漏主流程、权限、异常、边界、数据一致性。
- 自查 steps/expected 是否逐条对应。
- 自查用例标题是否可读、互不重复、没有空节点。

信息不足处理：
- 若上文含有效的 MCP 查证摘要，以摘要为准补足用例；摘要仍缺的条目在 summary 中列明「文档未覆盖」，**不得**用大批量无关用例填充。
- 若无有效文档摘录，细节缺失时可做最小必要合理假设后继续生成，不要因为信息不全而减少覆盖面；在 summary 中注明关键假设。

需求如下：
{requirement}"""


def build_plan_test_case_modules_prompt(requirement: str) -> str:
    """对齐 `planTestCaseModules`（TS 约 683–696）。"""
    return f"""你是资深测试架构师。请先根据需求拆解测试用例脑图的一级模块骨架。

目标：
- 只输出一级模块规划，不要生成具体测试用例。
- 默认拆成 4-7 个一级模块；需求很小时不少于 3 个，复杂需求可以 8 个。
- 模块标题要短、可作为脑图一级节点，不能带 @ 前缀。
- 每个模块要给出该模块的测试范围描述和关键风险点。
- id 使用小写英文、数字、中划线或下划线，保证模块间唯一。
- 最终只输出结构化 JSON，字段固定为 summary/modules。
- modules[] 每项**必须**使用键名：id、title、description（测试范围描述）、riskPoints（字符串数组，多条风险）。**禁止**用 scope、risk 等别名代替 description、riskPoints。

文档驱动（当上文含有效的 MCP 查证摘要时）：
- 一级模块必须贴合摘要中的业务域、流程或能力划分；description、riskPoints 应转述摘要中的具体需求句，避免仅用「功能测试」「安全」「兼容性」等空洞标签拼凑。

{COVERAGE_GUIDE}

需求如下：
{requirement}"""


def build_generate_module_test_cases_prompt(
    requirement: str,
    module: TestCaseModulePlan,
    modules: list[TestCaseModulePlan],
) -> str:
    """对齐 `generateModuleTestCases`（TS 约 719–742）。调用方宜传入已 `normalize_modules` 的 module。"""
    raw_title = re.sub(r"^@", "", (module.get("title") or "").strip()).strip()
    if not raw_title:
        raise ValueError("module 必须包含非空 title（normalize_modules 在输入全空时会回填默认模块，这里显式拦截）")

    target_list = normalize_modules([module])
    target_module = target_list[0]
    all_modules = normalize_modules(modules)

    lines = [f"{index + 1}. {item.get('title', '')}：{item.get('description', '')}" for index, item in enumerate(all_modules)]
    module_lines = "\n".join(lines)
    risks = target_module.get("riskPoints") or []
    risk_text = "、".join(str(r) for r in risks if str(r).strip()) if risks else "主流程、异常、边界、权限、数据一致性"
    title = target_module.get("title") or ""

    return f"""你是资深测试架构师。现在只为指定一级模块生成可执行测试用例。

整体需求：
{requirement}

一级模块清单：
{module_lines}

当前只处理模块：
- 标题：{title}
- 范围：{target_module.get("description", "")}
- 风险点：{risk_text}

文档驱动（当上文含有效的 MCP 查证摘要时）：
- 用例的 topic、steps、expected 必须落在新模块职责与摘要中相关条款上；禁止撰写摘要未涉及的另一套业务故事或泛化「同类系统」场景。

生成要求：
- 只生成“{title}”模块内的用例，不要扩散到其他一级模块。
- 默认生成 6-10 条高价值用例；模块很小时不少于 4 条，复杂模块可超过 10 条。
- cases[].category 统一写为“{title}”，不要带 @ 前缀。
- cases[].topic 不要包含 [P0]/[P1]/[P2]/[P3] 前缀，优先级只写在 priority 字段。

{TEST_CASE_GENERATION_GUIDE}

{COVERAGE_GUIDE}

{STRUCTURED_OUTPUT_GUIDE}"""


def build_chat_and_update_mind_map_prompt(messages: Sequence[Any], current_mind_map: dict[str, Any]) -> str:
    """对齐 `chatAndUpdateMindMap`（TS 约 767–785）。"""
    history = serialize_messages(messages)
    mind_json = json.dumps(current_mind_map, ensure_ascii=False)
    return f"""你是测试用例脑图助手。你的职责是根据用户连续对话，增删改当前脑图。

规则：
1. 先判断用户意图：新增、删除、改名、调整优先级、补充场景、质量审查或澄清。
2. 你只能基于“当前脑图”进行修改，保留未被要求变更的节点；除非用户明确要求重做，不要整体重写。
3. 输出的 mindMap 必须是完整树，而不是增量 patch。
4. 每个节点必须包含 data.text 和 children；叶子节点 children 使用 []。
5. 新增用例必须遵守：
   - 类别节点用 @ 开头；前置条件节点不要把 ! 写进 data.text，使用 data.tag: ["前置"] 标识。
   - 用例节点不要把 [P0]/[P1]/[P2]/[P3] 写进 data.text；优先级必须写入 data.priority，并同步放入 data.tag 数组。
   - 测试步骤和期望结果按父子结构组织，并逐条编号对应。
6. 删除或修改时要精准命中用户指定范围，避免误删相邻类别或前置条件。
7. assistantReply 用 1-2 句简洁中文说明本轮做了什么改动；如果用户要求不清晰，先提出澄清问题，同时尽量保持脑图不变。

当前脑图(JSON)：
{mind_json}

历史对话：
{history}"""
