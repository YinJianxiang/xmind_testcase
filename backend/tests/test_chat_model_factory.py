"""§6.3 create_chat_model / gpt-5 temperature 规则。"""

from __future__ import annotations

from unittest.mock import patch

from app.services import chat_model as cm


def test_model_supports_custom_temperature_aligned_ts_regex():
    assert not cm.model_supports_custom_temperature("gpt-5")
    assert not cm.model_supports_custom_temperature("GPT-5")
    assert not cm.model_supports_custom_temperature("gpt-5-mini")
    assert not cm.model_supports_custom_temperature("gpt-5.1")
    assert cm.model_supports_custom_temperature("")
    assert cm.model_supports_custom_temperature("gpt-51")
    assert cm.model_supports_custom_temperature("gpt-4.1-mini")
    assert cm.model_supports_custom_temperature("gpt-4o-mini")


class _DummySettings:
    openai_api_key: str | None = "sk-test"
    openai_model: str | None = None
    openai_base_url: str | None = None


@patch.object(cm, "ChatOpenAI")
def test_create_chat_model_default_and_temperature(mock_chat):
    dummy = _DummySettings()
    dummy.openai_model = None
    cm.create_chat_model(dummy)
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["model"] == cm.DEFAULT_MODEL
    assert kwargs["temperature"] == 0.2
    assert kwargs["api_key"] == "sk-test"


@patch.object(cm, "ChatOpenAI")
def test_create_chat_model_gpt5_omits_temperature(mock_chat):
    dummy = _DummySettings()
    dummy.openai_model = "gpt-5.1-mini"
    cm.create_chat_model(dummy)
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["model"] == "gpt-5.1-mini"
    assert "temperature" not in kwargs


@patch.object(cm, "ChatOpenAI")
def test_create_chat_model_base_url_trimmed(mock_chat):
    dummy = _DummySettings()
    dummy.openai_base_url = "  https://example.com/v1  "
    cm.create_chat_model(dummy)
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["base_url"] == "https://example.com/v1"


@patch.object(cm, "ChatOpenAI")
def test_create_chat_model_empty_base_url_omitted(mock_chat):
    dummy = _DummySettings()
    dummy.openai_base_url = "   "
    cm.create_chat_model(dummy)
    kwargs = mock_chat.call_args.kwargs
    assert "base_url" not in kwargs
