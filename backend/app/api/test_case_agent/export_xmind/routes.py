"""POST /api/test-case-agent/export-xmind。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

import app.api.test_case_agent.common as common
from app.schemas.agent_io import ExportXmindRequest
from app.services.xmind_export import build_xmind_zip, content_disposition_filename

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def post_export_xmind(request: Request) -> Any:
    """不要求 OPENAI_API_KEY（对齐现网）。"""
    try:
        body = await request.json()
    except Exception:
        logger.warning("POST /export-xmind JSON 解析失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})
    try:
        req = ExportXmindRequest.model_validate(body)
    except ValidationError:
        logger.warning("POST /export-xmind 参数校验失败")
        return JSONResponse(status_code=400, content={"error": "请求参数不合法"})

    mind_dict = req.mind_map.model_dump(mode="python")
    cases_dicts: list[dict[str, Any]] | None = None
    if req.test_cases:
        cases_dicts = [c.model_dump(by_alias=True) for c in req.test_cases]

    sheet_title = (req.title or "").strip() or (req.mind_map.data.text or "测试用例")

    logger.info(
        "POST /export-xmind 开始 title=%s cases=%s",
        sheet_title[:80],
        len(cases_dicts or []),
    )
    try:
        blob = build_xmind_zip(mind_dict, cases_dicts, req.title)
        logger.info("POST /export-xmind 成功 bytes=%s", len(blob))
    except Exception as e:
        logger.exception("POST /export-xmind 失败: %s", e)
        return common._handle_unknown(e)

    return Response(
        content=blob,
        media_type="application/vnd.xmind.workbook",
        headers={"Content-Disposition": content_disposition_filename(sheet_title)},
    )
