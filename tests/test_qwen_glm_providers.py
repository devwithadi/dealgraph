from __future__ import annotations

import os
from unittest.mock import MagicMock
import httpx
import pytest

from app.analysis.providers import (
    DEFAULT_DASHSCOPE_MODEL,
    DEFAULT_DASHSCOPE_SCREENING_MODEL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_DEEPSEEK_SCREENING_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_SCREENING_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    DEFAULT_OPENROUTER_SCREENING_MODEL,
    DEFAULT_ZHIPU_MODEL,
    DEFAULT_ZHIPU_SCREENING_MODEL,
    MODEL_ALIASES,
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


def test_all_model_aliases_are_mapped_correctly() -> None:
    expected_aliases = {
        # OpenAI
        "luna": "gpt-5-luna",
        "terra": "gpt-5-terra",
        "sol": "gpt-5-sol",
        "strawberry": "o1",
        "o3-mini": "o3-mini",
        "o1": "o1",
        "o1-mini": "o1-mini",
        "orion": "gpt-4.5-preview",
        "gpt-4.5": "gpt-4.5-preview",
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
        # Qwen
        "qwen-2.5-72b": "qwen/qwen-2.5-72b-instruct",
        "qwen-2.5-32b": "qwen/qwen-2.5-32b-instruct",
        "qwen-2.5-coder-32b": "qwen/qwen-2.5-coder-32b-instruct",
        "qwen-max": "qwen-max",
        "qwen-plus": "qwen-plus",
        "qwen-turbo": "qwen-turbo",
        # GLM
        "glm-4": "glm-4",
        "glm-4-plus": "glm-4-plus",
        "glm-4-air": "glm-4-air",
        "glm-5": "glm-5",
        # DeepSeek
        "deepseek-v3": "deepseek-chat",
        "deepseek-r1": "deepseek-reasoner",
        # Claude
        "claude-3.5-sonnet": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "claude-3.5-haiku": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        # Llama
        "llama-3.3-70b": "us.meta.llama3-3-70b-instruct-v1:0",
        "llama-3.1-70b": "us.meta.llama3-1-70b-instruct-v1:0",
        "llama-3.1-8b": "us.meta.llama3-1-8b-instruct-v1:0",
        # Nova
        "nova-pro": "amazon.nova-pro-v1:0",
        "nova-lite": "amazon.nova-lite-v1:0",
        "nova-micro": "amazon.nova-micro-v1:0",
    }
    for alias, expected in expected_aliases.items():
        assert MODEL_ALIASES.get(alias) == expected
        assert resolve_model_id(alias, "default-model") == expected
        assert resolve_model_id(alias.upper(), "default-model") == expected
        assert resolve_model_id(f"  {alias}  ", "default-model") == expected


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
    for provider in (
        "OPENROUTER",
        "DEEPSEEK",
        "DASHSCOPE",
        "ZHIPU",
        "OLLAMA",
    ):
        monkeypatch.delenv(f"{provider}_SCREENING_MODEL", raising=False)
        monkeypatch.delenv(f"{provider}_MODEL", raising=False)

    # Defaults
    assert screening_model_for(AIProvider.OPENROUTER) == DEFAULT_OPENROUTER_SCREENING_MODEL
    assert model_for(AIProvider.OPENROUTER) == DEFAULT_OPENROUTER_MODEL
    assert screening_model_for(AIProvider.DEEPSEEK) == DEFAULT_DEEPSEEK_SCREENING_MODEL
    assert model_for(AIProvider.DEEPSEEK) == DEFAULT_DEEPSEEK_MODEL
    assert screening_model_for(AIProvider.DASHSCOPE) == DEFAULT_DASHSCOPE_SCREENING_MODEL
    assert model_for(AIProvider.DASHSCOPE) == DEFAULT_DASHSCOPE_MODEL
    assert screening_model_for(AIProvider.ZHIPU) == DEFAULT_ZHIPU_SCREENING_MODEL
    assert model_for(AIProvider.ZHIPU) == DEFAULT_ZHIPU_MODEL
    assert screening_model_for(AIProvider.OLLAMA) == DEFAULT_OLLAMA_SCREENING_MODEL
    assert model_for(AIProvider.OLLAMA) == DEFAULT_OLLAMA_MODEL

    # Overrides with aliases
    assert screening_model_for(AIProvider.DASHSCOPE, "qwen-2.5-32b") == "qwen/qwen-2.5-32b-instruct"
    assert model_for(AIProvider.ZHIPU, "glm-5") == "glm-5"
    assert model_for(AIProvider.DEEPSEEK, "deepseek-r1") == "deepseek-reasoner"


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

    assert _provider_url(AIProvider.OPENROUTER) == "https://openrouter.ai/api/v1/chat/completions"
    assert _provider_url(AIProvider.DEEPSEEK) == "https://api.deepseek.com/v1/chat/completions"
    assert _provider_url(AIProvider.DASHSCOPE) == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert _provider_url(AIProvider.ZHIPU) == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert _provider_url(AIProvider.OLLAMA) == "http://localhost:11434/v1/chat/completions"

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


def test_model_json_execution_for_all_providers(monkeypatch) -> None:
    providers = [
        (AIProvider.OPENROUTER, "OPENROUTER_API_KEY", "qwen/qwen-2.5-72b-instruct"),
        (AIProvider.DEEPSEEK, "DEEPSEEK_API_KEY", "deepseek-chat"),
        (AIProvider.DASHSCOPE, "DASHSCOPE_API_KEY", "qwen-plus"),
        (AIProvider.ZHIPU, "ZHIPU_API_KEY", "glm-4-plus"),
        (AIProvider.OLLAMA, "OLLAMA_API_KEY", "qwen2.5:latest"),
    ]

    for provider, env_var, model_name in providers:
        monkeypatch.setenv(env_var, f"test-{env_var}")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"provider_result": "success"}'}}]},
                request=request,
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        payload = model_json(
            "Test diligence prompt",
            provider=provider,
            model=model_name,
            max_tokens=400,
            stage="synthesis",
            client=client,
        )
        assert payload == {"provider_result": "success"}


def test_provider_error_handling(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal error"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(failing_handler))
    with pytest.raises(AppError, match="DeepSeek synthesis unavailable"):
        model_json(
            "prompt",
            provider=AIProvider.DEEPSEEK,
            model="deepseek-chat",
            max_tokens=100,
            stage="synthesis",
            client=client,
        )


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


def test_openai_luna_and_terra_reasoning_effort(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    captured_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(body)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"status": "ok"}'}}]},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    # 1. Luna (Screening - fast non-reasoning model)
    res_luna = model_json(
        "Screen candidate",
        provider=AIProvider.OPENAI,
        model=resolve_model_id("luna", "default"),
        max_tokens=300,
        stage="screening",
        client=client,
    )
    assert res_luna == {"status": "ok"}
    req_luna = captured_requests[-1]
    assert req_luna["model"] == "gpt-5-luna"
    assert req_luna["max_completion_tokens"] == 300
    assert "max_tokens" not in req_luna
    assert req_luna["temperature"] == 0.1
    assert "reasoning_effort" not in req_luna

    # 2. Terra (Synthesis - reasoning model with default low effort)
    res_terra = model_json(
        "Synthesize memo",
        provider=AIProvider.OPENAI,
        model=resolve_model_id("terra", "default"),
        max_tokens=4096,
        stage="synthesis",
        client=client,
    )
    assert res_terra == {"status": "ok"}
    req_terra = captured_requests[-1]
    assert req_terra["model"] == "gpt-5-terra"
    assert req_terra["max_completion_tokens"] == 4096
    assert "max_tokens" not in req_terra
    assert "temperature" not in req_terra
    assert req_terra["reasoning_effort"] == "low"

    # 3. Terra with custom OPENAI_REASONING_EFFORT
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")
    res_terra_custom = model_json(
        "Synthesize memo custom",
        provider=AIProvider.OPENAI,
        model=resolve_model_id("terra", "default"),
        max_tokens=4096,
        stage="synthesis",
        client=client,
    )
    assert res_terra_custom == {"status": "ok"}
    req_terra_custom = captured_requests[-1]
    assert req_terra_custom["reasoning_effort"] == "medium"


