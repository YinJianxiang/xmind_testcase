"""API 层 4xx/5xx 分支（mock 服务，不调模型）。"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@patch("app.api.test_case_agent._openai_key_missing", return_value=False)
@patch("app.api.test_case_agent.plan_test_case_modules")
def test_plan_400_empty_requirement(mock_plan, _a):
    mock_plan.side_effect = AssertionError("should not call")
    r = client.post("/api/test-case-agent/plan", json={"requirement": "   "})
    assert r.status_code == 400
    assert "requirement" in r.json().get("error", "")


@patch("app.api.test_case_agent._openai_key_missing", return_value=True)
def test_plan_500_no_key(_k):
    r = client.post("/api/test-case-agent/plan", json={"requirement": "x"})
    assert r.status_code == 500
    assert "OPENAI_API_KEY" in r.json().get("error", "")


@patch("app.api.test_case_agent._openai_key_missing", return_value=False)
@patch("app.api.test_case_agent.plan_test_case_modules")
def test_plan_200(mock_plan, _k):
    mock_plan.return_value = {"summary": "s", "modules": [], "mindMap": {"data": {"text": "@测试用例"}, "children": []}}
    r = client.post("/api/test-case-agent/plan", json={"requirement": "登录"})
    assert r.status_code == 200
    assert r.json()["summary"] == "s"


def test_export_no_api_key_needed():
    r = client.post(
        "/api/test-case-agent/export-xmind",
        json={"mindMap": {"data": {"text": "标题"}, "children": []}},
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/vnd.xmind.workbook")


def test_build_xmind_zip_pk_header():
    import zipfile
    from io import BytesIO

    from app.services.xmind_export import build_xmind_zip

    mind = {"data": {"text": "@根"}, "children": []}
    z = build_xmind_zip(mind, None, None)
    assert z[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(z)) as zf:
        assert "content.json" in zf.namelist()
        assert "metadata.json" in zf.namelist()


@patch("app.api.test_case_agent._openai_key_missing", return_value=False)
@patch("app.api.test_case_agent.fetch_plan_mcp_document_brief")
def test_plan_requirement_source_200(mock_fetch, _k):
    mock_fetch.return_value = {
        "mcpDocumentBrief": "doc摘",
        "mcpDocumentToolRaw": [
            {
                "index": 0,
                "name": "docx_v1_document_rawContent",
                "tool_call_id": "call_1",
                "content": '{"raw": true}',
            },
        ],
    }
    r = client.post(
        "/api/test-case-agent/plan/requirement-source",
        json={"requirement": "见 https://x.feishu.cn/wiki/abc"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("mcpDocumentBrief") == "doc摘"
    raw = body.get("mcpDocumentToolRaw")
    assert isinstance(raw, list) and len(raw) == 1
    assert raw[0].get("name") == "docx_v1_document_rawContent"
    assert raw[0].get("toolCallId") == "call_1"
    assert raw[0].get("content") == '{"raw": true}'


@patch("app.api.test_case_agent._openai_key_missing", return_value=False)
@patch("app.api.test_case_agent.fetch_plan_mcp_document_brief")
def test_plan_requirement_source_200_no_tool_raw(mock_fetch, _k):
    mock_fetch.return_value = {"mcpDocumentBrief": "仅摘要", "mcpDocumentToolRaw": None}
    r = client.post(
        "/api/test-case-agent/plan/requirement-source",
        json={"requirement": "无链接"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("mcpDocumentBrief") == "仅摘要"
    assert body.get("mcpDocumentToolRaw") is None


@patch("app.api.test_case_agent._openai_key_missing", return_value=False)
@patch("app.api.test_case_agent.plan_modules_without_skeleton")
def test_plan_modules_only_200(mock_mod, _k):
    mock_mod.return_value = {"summary": "s", "modules": []}
    r = client.post(
        "/api/test-case-agent/plan/modules",
        json={"requirement": "r", "mcpDocumentBrief": "pref"},
    )
    assert r.status_code == 200
    assert r.json()["summary"] == "s"
    mock_mod.assert_called_once()


def test_plan_skeleton_200():
    mod = {
        "id": "m1",
        "title": "模块A",
        "description": "范围",
        "riskPoints": ["r1"],
    }
    r = client.post("/api/test-case-agent/plan/skeleton", json={"modules": [mod]})
    assert r.status_code == 200
    j = r.json()
    assert "mindMap" in j
    assert j["mindMap"]["data"]["text"]
