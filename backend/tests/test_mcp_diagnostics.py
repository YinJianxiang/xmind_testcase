"""GET /api/test-case-agent/mcp-diagnostics（不测真实 MCP 连接）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_mcp_diagnostics_without_connect(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/test-case-agent/mcp-diagnostics")
    assert r.status_code == 200
    data = r.json()
    assert data["mcp_json_exists"] is False
    assert data["servers"] == []
    assert data["connect_probe"] is None
    assert data["should_use_mcp_examples"]["plain_text"] is False
    assert data["should_use_mcp_examples"]["https_url"] is True
