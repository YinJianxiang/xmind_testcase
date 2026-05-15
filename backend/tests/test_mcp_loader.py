"""``mcp_loader``：正则与 JSON 映射。"""

import json
from pathlib import Path

import pytest

from app.services import mcp_loader


def test_should_use_mcp_url_and_keyword():
    assert mcp_loader.should_use_mcp("see https://wiki.example.com/doc")
    assert mcp_loader.should_use_mcp("需求链接在 confluence")
    assert mcp_loader.should_use_mcp("https://x.feishu.cn/docx/abc")
    assert not mcp_loader.should_use_mcp("纯文本需求无链接")


def test_mcp_system_prompt_suffix_dingtalk_doc_link():
    url = "https://alidocs.dingtalk.com/i/nodes/abcd1234efgh5678ijkl9012mnop3456?q=1"
    s = mcp_loader.mcp_system_prompt_suffix_for_user_prompt(f"需求 {url} 请生成用例")
    assert "钉钉" in s and "飞书" in s
    assert mcp_loader.mcp_system_prompt_suffix_for_user_prompt("无外链") == ""


def test_mcp_system_prompt_suffix_feishu_doc_link():
    url = "https://sample.feishu.cn/wiki/AbCdEfGh123"
    s = mcp_loader.mcp_system_prompt_suffix_for_user_prompt(f"看 {url} 写用例")
    assert "飞书" in s
    assert "feishu.cn" in s


def test_load_mcp_servers_config_stdio_and_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fs": {"type": "stdio", "command": "npx", "args": ["-y", "pkg"], "env": {"A": "1"}},
                    "remote": {"type": "http", "url": "https://x/mcp", "headers": {"H": "v"}},
                    "sse1": {"transport": "sse", "url": "https://y/sse"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = mcp_loader.load_mcp_servers_config()
    assert "fs" in out
    assert out["fs"]["transport"] == "stdio"
    assert out["fs"]["command"] == "npx"
    assert out["fs"]["args"] == ["-y", "pkg"]
    assert out["fs"]["env"] == {"A": "1"}

    assert out["remote"]["transport"] == "http"
    assert out["remote"]["url"] == "https://x/mcp"
    assert out["remote"]["headers"] == {"H": "v"}

    assert out["sse1"]["transport"] == "sse"


def test_load_mcp_stdio_without_explicit_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """与 Cursor / @larksuiteoapi/lark-mcp 常见写法一致：仅有 command + args。"""
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "lark-mcp": {
                        "command": "npx",
                        "args": ["-y", "@larksuiteoapi/lark-mcp", "mcp", "-a", "x", "-s", "y"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = mcp_loader.load_mcp_servers_config()
    assert "lark-mcp" in out
    assert out["lark-mcp"]["transport"] == "stdio"
    assert out["lark-mcp"]["command"] == "npx"


def test_load_mcp_streamable_http_maps_to_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gw": {"type": "streamable-http", "url": "https://example.com/mcp?k=1"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = mcp_loader.load_mcp_servers_config()
    assert out["gw"]["transport"] == "http"
    assert out["gw"]["url"].startswith("https://example.com/mcp")


def test_load_mcp_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    assert mcp_loader.load_mcp_servers_config() == {}


def test_load_mcp_stdio_expands_env_in_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LARK_MCP_APP_ID", "aid")
    monkeypatch.setenv("LARK_MCP_APP_SECRET", "sec")
    monkeypatch.setenv("LARK_MCP_USER_ACCESS_TOKEN", "uat")
    (tmp_path / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "lark-mcp": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "@larksuiteoapi/lark-mcp",
                            "mcp",
                            "-a",
                            "${LARK_MCP_APP_ID}",
                            "-s",
                            "${LARK_MCP_APP_SECRET}",
                            "-u",
                            "${LARK_MCP_USER_ACCESS_TOKEN}",
                        ],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = mcp_loader.load_mcp_servers_config()
    assert out["lark-mcp"]["args"] == [
        "-y",
        "@larksuiteoapi/lark-mcp",
        "mcp",
        "-a",
        "aid",
        "-s",
        "sec",
        "-u",
        "uat",
    ]
