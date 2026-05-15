"""
对齐 next-ai-test-cases `testCaseAgent.ts` 内 `createModel`（约 420–433 行）。
"""

from __future__ import annotations

import logging
import re

from langchain_openai import ChatOpenAI

from app.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

# 进程内只打一次模型 / URL，避免每个请求刷屏
_chat_model_target_logged = False

# TS: !/^gpt-5(?:\.|-|$)/i
_GPT5_NO_CUSTOM_TEMPERATURE = re.compile(r"^gpt-5(?:\.|-|$)", re.IGNORECASE)

DEFAULT_MODEL = "gpt-4.1-mini"


def model_supports_custom_temperature(model: str) -> bool:
    """为 gpt-5 系列不传 temperature（与 TS `supportsCustomTemperature` 一致）。"""
    stripped = model.strip()
    if not stripped:
        return True
    return _GPT5_NO_CUSTOM_TEMPERATURE.match(stripped) is None


def create_chat_model(settings: Settings | None = None) -> ChatOpenAI:
    """
    从 ``Settings``（环境变量 / ``.env``）构造 ``ChatOpenAI``。
    默认模型 ``gpt-4.1-mini``；若 ``OPENAI_BASE_URL``（非空）则走兼容网关。
    """
    s = settings if settings is not None else default_settings
    model = (s.openai_model or "").strip() or DEFAULT_MODEL
    api_key = s.openai_api_key
    base_raw = (s.openai_base_url or "").strip()
    base_url = base_raw if base_raw else None

    kwargs: dict[str, object] = {
        "model": model,
        "api_key": api_key,
    }
    if base_url is not None:
        kwargs["base_url"] = base_url
    if model_supports_custom_temperature(model):
        kwargs["temperature"] = 0.2

    global _chat_model_target_logged
    if not _chat_model_target_logged:
        url_logged = (
            base_url
            if base_url is not None
            else "(未设置 OPENAI_BASE_URL，使用 OpenAI SDK 默认)"
        )
        logger.info("创建 ChatOpenAI: model=%s base_url=%s", model, url_logged)
        _chat_model_target_logged = True

    return ChatOpenAI(**kwargs)
