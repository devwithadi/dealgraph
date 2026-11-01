from __future__ import annotations

import os
from unittest.mock import MagicMock
import httpx
import pytest

from app.analysis.providers import (
    PROVIDER_CONFIGS,
    _parse_json,
    _provider_url,
    model_for,
    model_json,
    resolve_model_id,
    screening_model_for,
    validate_provider_config,
)
from app.core.errors import AppError
from app.core.urls import PublicUrlError, validate_public_url
from app.domain.enums import AIProvider


def test_resolve_model_id_passthrough() -> None:
    test_models = [
        "gpt-4o",
        "gpt-4.1",
        "qwen/qwen-2.5-72b-instruct",
        "qwen-plus",
        "glm-4-plus",
        "deepseek-chat",
        "deepseek-reasoner",
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "amazon.nova-pro-v1:0",
    ]
    for model_name in test_models:
        assert resolve_model_id(model_name, "default-model") == model_name
        assert resolve_model_id(f"  {model_name}  ", "default-model") == model_name


def test_parse_json_strips_thinking_tags() -> None:
    # DeepSeek-R1 style output with thinking blocks
    raw_response = (
        "<think>\n"
        "Let's evaluate the investment memo for this AI startup.\n"
        "We need to return JSON format with high fidelity.\n"
        "</think>\n"
        '{"status": "approved", "score": 95.0, "reason": "strong moat"}'
    )
    result = _parse_json(raw_response)
    assert result == {"status": "approved", "score": 95.0, "reason": "strong moat"}

    # Fenced json with thinking blocks
    raw_fenced = (
        "<think>Analyzing candidate...</think>\n"
        "```json\n"
        '{"decisions": [{"slug": "acme", "advance": true}]}\n'
        "```"
    )
    assert _parse_json(raw_fenced) == {"decisions": [{"slug": "acme", "advance": True}]}

    # Multiple thinking tags
    raw_multi = (
        "<think>Initial thoughts</think>\n"
        "<think>Refined thoughts</think>\n"
        '{"valid": true}'
    )
    assert _parse_json(raw_multi) == {"valid": True}


def test_provider_defaults_and_env_overrides(monkeypatch) -> None:
    # Clear env vars
    for provider_name in (
        "OPENROUTER",
        "DEEPSEEK",
        "DASHSCOPE",
        "ZHIPU",
        "OLLAMA",
    ):
        monkeypatch.delenv(f"{provider_name}_SCREENING_MODEL", raising=False)
        monkeypatch.delenv(f"{provider_name}_MODEL", raising=False)

    # Defaults
    assert screening_model_for(AIProvider.OPENROUTER) == PROVIDER_CONFIGS[AIProvider.OPENROUTER].default_screening_model
    assert model_for(AIProvider.OPENROUTER) == PROVIDER_CONFIGS[AIProvider.OPENROUTER].default_synthesis_model
    assert screening_model_for(AIProvider.DEEPSEEK) == PROVIDER_CONFIGS[AIProvider.DEEPSEEK].default_screening_model
    assert model_for(AIProvider.DEEPSEEK) == PROVIDER_CONFIGS[AIProvider.DEEPSEEK].default_synthesis_model
    assert screening_model_for(AIProvider.DASHSCOPE) == PROVIDER_CONFIGS[AIProvider.DASHSCOPE].default_screening_model
    assert model_for(AIProvider.DASHSCOPE) == PROVIDER_CONFIGS[AIProvider.DASHSCOPE].default_synthesis_model
    assert screening_model_for(AIProvider.ZHIPU) == PROVIDER_CONFIGS[AIProvider.ZHIPU].default_screening_model
    assert model_for(AIProvider.ZHIPU) == PROVIDER_CONFIGS[AIProvider.ZHIPU].default_synthesis_model
    assert screening_model_for(AIProvider.OLLAMA) == PROVIDER_CONFIGS[AIProvider.OLLAMA].default_screening_model
    assert model_for(AIProvider.OLLAMA) == PROVIDER_CONFIGS[AIProvider.OLLAMA].default_synthesis_model

    # Env overrides
    monkeypatch.setenv("DASHSCOPE_SCREENING_MODEL", "qwen-2.5-32b")
    monkeypatch.setenv("ZHIPU_MODEL", "glm-5")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    assert screening_model_for(AIProvider.DASHSCOPE) == "qwen-2.5-32b"
    assert model_for(AIProvider.ZHIPU) == "glm-5"
    assert model_for(AIProvider.DEEPSEEK) == "deepseek-reasoner"

    # CLI overrides
    assert screening_model_for(AIProvider.DASHSCOPE, "qwen-max") == "qwen-max"
    assert model_for(AIProvider.ZHIPU, "glm-4-plus") == "glm-4-plus"


def test_validate_public_url_with_local_llm_endpoints() -> None:
    # Localhost allowed when allow_local=True
    ollama_url = "http://localhost:11434/v1/chat/completions"
    validated = validate_public_url(
        ollama_url,
        schemes={"http", "https"},
        ports={80, 443, 11434},
        allow_local=True,
    )
    assert validated == ollama_url

    # 127.0.0.1 allowed when allow_local=True
    ip_url = "http://127.0.0.1:11434/v1/chat/completions"
    validated_ip = validate_public_url(
        ip_url,
        schemes={"http", "https"},
        ports={80, 443, 11434},
        allow_local=True,
    )
    assert validated_ip == ip_url

    # Rejection when allow_local=False
    with pytest.raises(PublicUrlError, match="Non-public target rejected"):
        validate_public_url(
            ollama_url,
            schemes={"http", "https"},
            ports={80, 443, 11434},
            allow_local=False,
        )


def test_provider_url_and_validation(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")

    assert _provider_url(AIProvider.OPENROUTER) == "https://openrouter.ai/api/v1"
    assert _provider_url(AIProvider.DEEPSEEK) == "https://api.deepseek.com/v1"
    assert _provider_url(AIProvider.DASHSCOPE) == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert _provider_url(AIProvider.ZHIPU) == "https://open.bigmodel.cn/api/paas/v4"
    assert _provider_url(AIProvider.OLLAMA) == "http://localhost:11434/v1"

    validate_provider_config(AIProvider.OPENROUTER)
    validate_provider_config(AIProvider.DEEPSEEK)
    validate_provider_config(AIProvider.DASHSCOPE)
    validate_provider_config(AIProvider.ZHIPU)
    validate_provider_config(AIProvider.OLLAMA)


def test_missing_api_keys_raise_app_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(AppError, match="OPENROUTER_API_KEY is required"):
        validate_provider_config(AIProvider.OPENROUTER)

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(AppError, match="DEEPSEEK_API_KEY is required"):
        validate_provider_config(AIProvider.DEEPSEEK)

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(AppError, match="DASHSCOPE_API_KEY is required"):
        validate_provider_config(AIProvider.DASHSCOPE)

    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    with pytest.raises(AppError, match="ZHIPU_API_KEY is required"):
        validate_provider_config(AIProvider.ZHIPU)


def test_invalid_base_urls_and_unknown_provider_handling(monkeypatch) -> None:
    from app.analysis.providers import _openai_url

    # _openai_url returns openai base url
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert "https://api.openai.com/v1" in _openai_url()

    # Invalid base URL with credentials
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://user:pass@dashscope.example.com")
    with pytest.raises(AppError, match="Invalid DASHSCOPE_BASE_URL"):
        validate_provider_config(AIProvider.DASHSCOPE)

    # Invalid scheme for non-local provider
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "http://dashscope.example.com")
    with pytest.raises(AppError, match="Invalid DASHSCOPE_BASE_URL"):
        validate_provider_config(AIProvider.DASHSCOPE)


def test_fenced_json_without_language_tag() -> None:
    raw = "```\n{\n  \"status\": \"ok\"\n}\n```"
    assert _parse_json(raw) == {"status": "ok"}

