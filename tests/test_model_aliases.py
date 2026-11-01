from __future__ import annotations

import pytest

from app.analysis.providers import (
    BEDROCK_MODEL_ALIASES,
    MODEL_ALIASES,
    PROVIDER_CONFIGS,
    is_reasoning_model,
    model_for,
    resolve_model_id,
    screening_model_for,
    validate_provider_config,
)
from app.core.errors import AppError
from app.domain.enums import AIProvider


def test_model_aliases_dicts_exist() -> None:
    assert isinstance(MODEL_ALIASES, dict)
    assert isinstance(BEDROCK_MODEL_ALIASES, dict)


def test_resolve_model_id_falls_back_to_default_when_none_or_empty() -> None:
    default_bedrock = PROVIDER_CONFIGS[AIProvider.BEDROCK].default_synthesis_model
    assert resolve_model_id(None, default_bedrock) == default_bedrock
    assert resolve_model_id("", default_bedrock) == default_bedrock
    assert resolve_model_id("   ", default_bedrock) == default_bedrock
    assert resolve_model_id(None, "amazon.nova-micro-v1:0") == "amazon.nova-micro-v1:0"


def test_resolve_model_id_passes_through_any_model_id_or_arn() -> None:
    custom_arn = "arn:aws:bedrock:us-east-1:123456789012:custom-model/test"
    assert resolve_model_id(custom_arn, "default-model") == custom_arn

    custom_id = "us.meta.llama3-3-70b-instruct-v1:0"
    assert resolve_model_id(custom_id, "default-model") == custom_id

    custom_openai = "gpt-4o"
    assert resolve_model_id(custom_openai, "default-model") == custom_openai


def test_screening_model_for_and_model_for_env_and_cli_overrides(monkeypatch) -> None:
    monkeypatch.delenv("BEDROCK_SCREENING_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    bedrock_cfg = PROVIDER_CONFIGS[AIProvider.BEDROCK]
    # Bedrock defaults
    assert screening_model_for(AIProvider.BEDROCK) == bedrock_cfg.default_screening_model
    assert model_for(AIProvider.BEDROCK) == bedrock_cfg.default_synthesis_model

    # Bedrock env overrides
    monkeypatch.setenv("BEDROCK_SCREENING_MODEL_ID", "amazon.nova-micro-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
    assert screening_model_for(AIProvider.BEDROCK) == "amazon.nova-micro-v1:0"
    assert model_for(AIProvider.BEDROCK) == "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

    # Bedrock CLI overrides (preempts env)
    assert screening_model_for(AIProvider.BEDROCK, "custom.screen.v1") == "custom.screen.v1"
    assert model_for(AIProvider.BEDROCK, "custom.synth.v1") == "custom.synth.v1"

    # OpenAI provider defaults and overrides
    monkeypatch.delenv("OPENAI_SCREENING_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    openai_cfg = PROVIDER_CONFIGS[AIProvider.OPENAI]
    assert screening_model_for(AIProvider.OPENAI) == openai_cfg.default_screening_model
    assert model_for(AIProvider.OPENAI) == openai_cfg.default_synthesis_model

    monkeypatch.setenv("OPENAI_SCREENING_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    assert screening_model_for(AIProvider.OPENAI) == "gpt-4o-mini"
    assert model_for(AIProvider.OPENAI) == "gpt-4o"

    assert screening_model_for(AIProvider.OPENAI, "o3-mini") == "o3-mini"
    assert model_for(AIProvider.OPENAI, "o1") == "o1"


def test_validate_provider_config_accepts_valid_overrides(monkeypatch) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "configured")
    monkeypatch.setenv("BEDROCK_SCREENING_MODEL_ID", "   ")
    # Without override, blank env fails
    with pytest.raises(AppError, match="model IDs cannot be empty"):
        validate_provider_config(AIProvider.BEDROCK)

    # With valid override, validation succeeds
    validate_provider_config(
        AIProvider.BEDROCK,
        screening_override="amazon.nova-micro-v1:0",
        synthesis_override="amazon.nova-pro-v1:0",
    )


def test_parse_json_handles_fenced_blocks_and_validates_dict() -> None:
    from app.analysis.providers import _parse_json

    # Standard json
    assert _parse_json('{"key": "value"}') == {"key": "value"}

    # Markdown fenced json
    assert _parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}
    assert _parse_json('```\n{"a": 1, "b": 2}\n```') == {"a": 1, "b": 2}

    # Non-dict error
    with pytest.raises(ValueError, match="JSON object"):
        _parse_json('["item1", "item2"]')


def test_openai_model_json_execution(monkeypatch) -> None:
    from app.analysis.providers import model_json
    import httpx

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"result": "success"}'}}]},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    payload = model_json(
        "test prompt",
        provider=AIProvider.OPENAI,
        model="gpt-4.1-mini",
        max_tokens=500,
        stage="synthesis",
        client=client,
    )
    assert payload == {"result": "success"}


def test_openai_model_json_missing_key_error(monkeypatch) -> None:
    from app.analysis.providers import model_json
    import httpx

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AppError, match="OPENAI_API_KEY is required"):
        model_json(
            "test prompt",
            provider=AIProvider.OPENAI,
            model="gpt-4.1-mini",
            max_tokens=500,
            stage="synthesis",
            client=httpx.Client(),
        )


def test_bedrock_json_error_handling() -> None:
    from app.analysis.providers import model_json
    from botocore.exceptions import ClientError
    import httpx

    class FailingBedrockClient:
        def converse(self, **_kwargs):
            raise ClientError(
                {"Error": {"Message": "ThrottlingException", "Code": "ThrottlingException"}},
                "converse",
            )

    with pytest.raises(AppError, match="Bedrock synthesis unavailable"):
        model_json(
            "test prompt",
            provider=AIProvider.BEDROCK,
            model="amazon.nova-lite-v1:0",
            max_tokens=500,
            stage="synthesis",
            client=httpx.Client(),
            bedrock_client=FailingBedrockClient(),
        )


def test_is_reasoning_model_detection() -> None:
    reasoning_cases = [
        "o1",
        "o1-mini",
        "o1-preview",
        "o3",
        "o3-mini",
        "deepseek-reasoner",
        "deepseek-r1",
        "DEEPSEEK-R1",
        "deepseek/deepseek-r1",
        "qwq",
        "qwq-32b",
        "qwen/qwq-32b-preview",
        "openai/o1",
        "openai/o3-mini",
        "r1",
    ]
    for model in reasoning_cases:
        assert is_reasoning_model(model) is True

    non_reasoning_cases = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.5",
        "gpt-4.5-preview",
        "deepseek-chat",
        "deepseek-v3",
        "amazon.nova-lite-v1:0",
        "amazon.nova-pro-v1:0",
        "claude-3.5-sonnet",
        "qwen-turbo",
        "qwen-plus",
        "glm-4-plus",
        "glm-4-air",
    ]
    for model in non_reasoning_cases:
        assert is_reasoning_model(model) is False


def test_openai_payload_reasoning_effort_and_token_handling(monkeypatch) -> None:
    import json
    import httpx
    from app.analysis.providers import model_json

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"analysis": "complete"}'}}]},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    # Supported non-reasoning models use deterministic sampling.
    model_json(
        "screening prompt",
        provider=AIProvider.OPENAI,
        model="gpt-4o-mini",
        max_tokens=600,
        stage="screening",
        client=client,
    )
    mini_req = captured_payloads[-1]
    assert mini_req["model"] == "gpt-4o-mini"
    assert mini_req["max_completion_tokens"] == 600
    assert "max_tokens" not in mini_req
    assert mini_req["temperature"] == 0
    assert "reasoning_effort" not in mini_req

    # Synthesis uses the same deterministic setting.
    model_json(
        "synthesis prompt",
        provider=AIProvider.OPENAI,
        model="gpt-4.1",
        max_tokens=1500,
        stage="synthesis",
        client=client,
    )
    synth_req = captured_payloads[-1]
    assert synth_req["model"] == "gpt-4.1"
    assert synth_req["max_completion_tokens"] == 1500
    assert synth_req["temperature"] == 0
    assert "reasoning_effort" not in synth_req

    # Test o1 (reasoning model) -> max_completion_tokens, reasoning_effort "low", no temperature
    model_json(
        "reasoning prompt",
        provider=AIProvider.OPENAI,
        model="o1",
        max_tokens=4096,
        stage="synthesis",
        client=client,
    )
    o1_req = captured_payloads[-1]
    assert o1_req["model"] == "o1"
    assert o1_req["max_completion_tokens"] == 4096
    assert "max_tokens" not in o1_req
    assert o1_req["reasoning_effort"] == "low"
    assert "temperature" not in o1_req

    # Test o3-mini (reasoning model) with custom OPENAI_REASONING_EFFORT
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    model_json(
        "reasoning prompt",
        provider=AIProvider.OPENAI,
        model="o3-mini",
        max_tokens=2048,
        stage="synthesis",
        client=client,
    )
    o3_req = captured_payloads[-1]
    assert o3_req["model"] == "o3-mini"
    assert o3_req["max_completion_tokens"] == 2048
    assert o3_req["reasoning_effort"] == "high"
    assert "temperature" not in o3_req
