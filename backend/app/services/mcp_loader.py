"""
对齐 ``testCaseAgent.ts``：`shouldUseMcp``（约 537–539）、``loadMcpServersConfig``（约 436–478）。
输出字典可直接用于 ``langchain_mcp_adapters.MultiServerMCPClient``（须含 ``transport``）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _expand_env_strings(obj: Any) -> Any:
    """将 ``${VAR}`` / ``$VAR`` 替换为环境变量（须已通过 dotenv 写入 ``os.environ``）。"""
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, list):
        return [_expand_env_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_env_strings(v) for k, v in obj.items()}
    return obj


def _parse_lark_stdio_a_s_u(expanded_args: list[Any]) -> tuple[str, str, str]:
    """从已 ``expandvars`` 后的 ``args`` 列表解析 Lark MCP 的 ``-a`` ``-s`` ``-u`` 值。"""
    app_id = ""
    secret = ""
    token = ""
    s = [str(x) for x in expanded_args]
    i = 0
    while i < len(s):
        if i + 1 >= len(s):
            break
        flag, val = s[i], s[i + 1]
        if flag == "-a":
            app_id = val
            i += 2
            continue
        if flag == "-s":
            secret = val
            i += 2
            continue
        if flag == "-u":
            token = val
            i += 2
            continue
        i += 1
    return (app_id, secret, token)


def _looks_like_lark_mcp_stdio_args(expanded_args: list[Any]) -> bool:
    for x in expanded_args:
        t = str(x)
        if "larksuiteoapi/lark-mcp" in t:
            return True
        # npx -y lark-mcp 等简短包名
        if t == "lark-mcp" or t.rstrip('"').endswith("lark-mcp"):
            return True
    return False


def _log_lark_stdio_effective_credentials(server_name: str, entry: dict[str, Any], expanded_args: list[Any]) -> None:
    """
    临时调试：记录即将交给子进程的 Lark MCP 实际参数（经 ``expandvars`` 后的 CLI，非裸环境变量）。

    若 ``-u`` 等仅写在 ``entry[\"env\"]`` 中而未出现在 args，则用展开后的 env 补全日志。
    """
    if not _looks_like_lark_mcp_stdio_args(expanded_args):
        return

    app_id, secret, token = _parse_lark_stdio_a_s_u(expanded_args)
    raw_env = entry.get("env")
    if isinstance(raw_env, dict):
        app_id = app_id or str(raw_env.get("LARK_MCP_APP_ID") or "")
        secret = secret or str(raw_env.get("LARK_MCP_APP_SECRET") or "")
        token = token or str(raw_env.get("LARK_MCP_USER_ACCESS_TOKEN") or "")

    logger.info(
        "load_mcp_servers_config: MCP Lark 子进程实际入参[%s] -a=%s -s=%s -u=%s",
        server_name,
        app_id,
        secret,
        token,
    )


_SHOULD_USE_MCP_URL = re.compile(r"https?://", re.IGNORECASE)
_SHOULD_USE_MCP_KW = re.compile(
    r"(confluence|kaptain|jira|wiki|需求链接|需求地址|文档地址|页面链接"
    r"|cf\.qunhequnhe\.com|kaptain\.qunhequnhe\.com"
    r"|alidocs\.dingtalk\.com|钉钉文档"
    r"|feishu\.cn|larksuite\.com|飞书文档|飞书链接|飞书知识库|知识库|飞书)",
    re.IGNORECASE,
)
# 钉钉在线文档：https://alidocs.dingtalk.com/i/nodes/{dentryUuid}
_DINGTALK_ALIDOCS_NODE = re.compile(
    r"https?://alidocs\.dingtalk\.com/i/nodes/[a-zA-Z0-9]+(?:\?[^\s]*)?",
    re.IGNORECASE,
)
# 飞书 / Lark：*.feishu.cn、主域 feishu.cn、*.larksuite.com 等
_FEISHU_LARK_DOC_URL = re.compile(
    r"https?://(?:[a-zA-Z0-9.-]+\.)?(?:feishu\.cn|larksuite\.com)(?:/[^\s]*)?",
    re.IGNORECASE,
)

_DINGTALK_FETCH_HINT = (
    " 当用户消息含钉钉文档链（https://alidocs.dingtalk.com/i/nodes/…）时，若 MCP 提供钉钉文档能力，"
    "须先调用名称中含 get_document_content（或等价「读钉钉文档」）的工具，参数为完整 URL，或仅 32 位 dentryUuid/nodeId；"
    "用返回的 Markdown 作为需求来源再输出 JSON。"
    " 注意：链接若带 doc_type=wiki_doc 等知识库/ Wiki 节点，与「钉钉在线文档」可能走不同接口；"
    "若拉取失败可尝试只传 nodeId，或确认该 MCP 是否支持知识库节点。"
    " 若当前仅接入了飞书等其他平台 MCP、没有钉钉读文档工具，则无法拉取该链接正文，不得假装已获取；"
    "应简要说明原因，并请用户改用飞书文档链接、或直接粘贴需求全文。"
)

_FEISHU_FETCH_HINT = (
    " 当用户消息含飞书 / Lark 文档或知识库链接（*.feishu.cn、*.larksuite.com 等）时，必须先根据当前 MCP "
    "已注册工具列表，选用能读取飞书云文档/知识库/wiki 的工具（名称常含 doc、wiki、document、bitable 等，以实际工具为准），"
    "传入文档链接或文档 token，**实际调用工具**取得正文后再做答；禁止在未调用工具前凭链接猜测正文。"
    "用返回的正文作为需求来源后再完成 JSON 输出；禁止编造未拉取到的内容。"
    " 注意：飞书 MCP 不能访问钉钉 alidocs.dingtalk.com 链接，此类链接需换文档源或由用户粘贴正文。"
    " 链接路径含 /wiki/ 时为知识库/wiki，优先使用 wiki_* 类工具；若使用 docx_builtin_search，"
    "参数 data.docs_types 仅能为以下英文小写枚举之一（可多选）：doc、sheet、slides、bitable、mindnote、file；"
    "禁止使用 document、wiki、docx 等非列出字面量。"
)


def should_use_mcp(prompt: str) -> bool:
    if not (prompt or "").strip():
        return False
    return bool(_SHOULD_USE_MCP_URL.search(prompt) or _SHOULD_USE_MCP_KW.search(prompt))


def mcp_system_prompt_suffix_for_user_prompt(user_text: str) -> str:
    """
    用户提示里含钉钉 / 飞书文档链接时，追加到 MCP Agent 的 system prompt，
    引导模型先通过对应 MCP 工具取正文再做题。
    """
    if not (user_text or "").strip():
        return ""
    parts: list[str] = []
    if _DINGTALK_ALIDOCS_NODE.search(user_text):
        parts.append(_DINGTALK_FETCH_HINT)
    if _FEISHU_LARK_DOC_URL.search(user_text):
        parts.append(_FEISHU_FETCH_HINT)
    if not parts:
        return ""
    return " " + " ".join(parts)


def load_mcp_servers_config() -> dict[str, dict[str, Any]]:
    """
    读 ``cwd/mcp.json``，映射为 MultiServerMCPClient 的 ``connections``。
    http/sse 显式带 ``transport``（TS 里 http 分支不带 transport，此处补上）。
    """
    dotenv_path = Path.cwd() / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path)
    else:
        load_dotenv()

    path = Path.cwd() / "mcp.json"
    if not path.is_file():
        logger.debug("mcp.json 不存在: %s", path.resolve())
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取或解析 mcp.json 失败: %s (%s)", path.resolve(), exc)
        return {}

    servers_any = parsed.get("mcpServers") if isinstance(parsed, dict) else None
    if not isinstance(servers_any, dict):
        logger.warning("mcp.json 缺少有效的 mcpServers: %s", path.resolve())
        return {}

    out: dict[str, dict[str, Any]] = {}
    for name, server_any in servers_any.items():
        if not isinstance(server_any, dict):
            continue
        mode = server_any.get("transport") or server_any.get("type")
        url_raw = server_any.get("url")
        cmd_raw = server_any.get("command")
        url = url_raw.strip() if isinstance(url_raw, str) and url_raw.strip() else ""
        cmd = cmd_raw.strip() if isinstance(cmd_raw, str) and cmd_raw.strip() else ""

        # 远程：显式 url（含 streamable-http、默认 http、以及仅写 url 的网关）
        if url:
            headers = server_any.get("headers")
            hdr: dict[str, str] = {}
            if isinstance(headers, dict):
                hdr = {str(k): str(v) for k, v in headers.items()}

            if mode == "sse":
                out[str(name)] = {"transport": "sse", "url": url, "headers": hdr}
            else:
                # http / streamable-http / 未标注 type 的 URL 服务
                out[str(name)] = {"transport": "http", "url": url, "headers": hdr}
            continue

        # 本地 stdio：显式 type=stdio，或仅写 command（与 Cursor / lark-mcp 示例一致）
        if mode == "stdio" or cmd:
            if not cmd:
                continue
            args_expanded = _expand_env_strings(list(server_any.get("args") or []))
            entry = {
                "transport": "stdio",
                "command": cmd,
                "args": args_expanded,
            }
            env = server_any.get("env")
            if isinstance(env, dict) and env:
                expanded = _expand_env_strings(env)
                entry["env"] = {str(k): str(v) for k, v in expanded.items()}
            _log_lark_stdio_effective_credentials(str(name), entry, args_expanded)
            out[str(name)] = entry
            continue

    if not out:
        logger.info("mcp.json 无可用 MCP server（检查 command/url 等字段） path=%s", path.resolve())
    else:
        logger.info("mcp.json 已加载 path=%s servers=%s", path.resolve(), list(out.keys()))
    return out
