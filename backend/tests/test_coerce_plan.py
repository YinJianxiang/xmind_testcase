from app.schemas.llm_output import PlanStructuredOutput, coerce_plan_llm_dict


def test_coerce_scope_risk_to_description_risk_points():
    raw = {
        "summary": "概览",
        "modules": [
            {
                "id": "a",
                "title": "登录",
                "scope": "账号与 token",
                "risk": "超时、重放",
            },
        ],
    }
    out = PlanStructuredOutput.model_validate(coerce_plan_llm_dict(raw))
    assert out.modules[0].description == "账号与 token"
    assert out.modules[0].riskPoints == ["超时", "重放"]


def test_coerce_string_risk_points_split():
    raw = {
        "summary": "",
        "modules": [
            {"id": "x", "title": "T", "description": "d", "riskPoints": "a,b；c"},
        ],
    }
    out = PlanStructuredOutput.model_validate(coerce_plan_llm_dict(raw))
    assert out.modules[0].riskPoints == ["a", "b", "c"]
