from __future__ import annotations

import pytest

from app.analysis.providers import (
    BEDROCK_MODEL_ALIASES,
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_BEDROCK_SCREENING_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_SCREENING_MODEL,
    model_for,
    resolve_model_id,
    screening_model_for,
    validate_provider_config,
)
from app.core.errors import AppError
from app.domain.enums import AIProvider


def test_all_specified_bedrock_aliases_are_present() -> None:
    expected_aliases = {
        "llama-3.3-70b": "us.meta.llama3-3-70b-instruct-v1:0",
        "llama-3.1-70b": "us.meta.llama3-1-70b-instruct-v1:0",
        "llama-3.1-8b": "us.meta.llama3-1-8b-instruct-v1:0",
        "nova-pro": "amazon.nova-pro-v1:0",
        "nova-lite": "amazon.nova-lite-v1:0",
        "nova-micro": "amazon.nova-micro-v1:0",
        "claude-3.5-sonnet": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "claude-3.5-haiku": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "mistral-large": "mistral.mistral-large-2407-v1:0",
    }
    for alias, expected_id in expected_aliases.items():
        assert BEDROCK_MODEL_ALIASES.get(alias) == expected_id
        assert resolve_model_id(alias, DEFAULT_BEDROCK_MODEL) == expected_id
        assert resolve_model_id(alias.upper(), DEFAULT_BEDROCK_MODEL) == expected_id
        assert resolve_model_id(f"  {alias}  ", DEFAULT_BEDROCK_MODEL) == expected_id


def test_resolve_model_id_falls_back_to_default_when_none_or_empty() -> None:
    assert resolve_model_id(None, DEFAULT_BEDROCK_MODEL) == DEFAULT_BEDROCK_MODEL
    assert resolve_model_id("", DEFAULT_BEDROCK_MODEL) == DEFAULT_BEDROCK_MODEL
    assert resolve_model_id("   ", DEFAULT_BEDROCK_MODEL) == DEFAULT_BEDROCK_MODEL
    assert resolve_model_id(None, "nova-micro") == "amazon.nova-micro-v1:0"


def test_resolve_model_id_passes_through_unaliased_ids() -> None:
    custom_arn = "arn:aws:bedrock:us-east-1:123456789012:custom-model/test"
    assert resolve_model_id(custom_arn, DEFAULT_BEDROCK_MODEL) == custom_arn


def test_screening_model_for_and_model_for_support_overrides(monkeypatch) -> None:
    monkeypatch.delenv("BEDROCK_SCREENING_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    # Defaults
    assert screening_model_for(AIProvider.BEDROCK) == DEFAULT_BEDROCK_SCREENING_MODEL
    assert model_for(AIProvider.BEDROCK) == DEFAULT_BEDROCK_MODEL

    # Overrides with aliases
    assert screening_model_for(AIProvider.BEDROCK, "nova-pro") == "amazon.nova-pro-v1:0"
    assert model_for(AIProvider.BEDROCK, "claude-3.5-sonnet") == "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

    # Overrides with exact IDs
    assert screening_model_for(AIProvider.BEDROCK, "custom.screen.v1") == "custom.screen.v1"
    assert model_for(AIProvider.BEDROCK, "custom.synth.v1") == "custom.synth.v1"

    # OpenAI provider
    monkeypatch.delenv("OPENAI_SCREENING_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert screening_model_for(AIProvider.OPENAI) == DEFAULT_OPENAI_SCREENING_MODEL
    assert model_for(AIProvider.OPENAI) == DEFAULT_OPENAI_MODEL
    assert screening_model_for(AIProvider.OPENAI, "gpt-4o-mini") == "gpt-4o-mini"
    assert model_for(AIProvider.OPENAI, "gpt-4o") == "gpt-4o"


def test_validate_provider_config_accepts_valid_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BEDROCK_SCREENING_MODEL_ID", "   ")
    # Without override, blank env fails
    with pytest.raises(AppError, match="model IDs cannot be empty"):
        validate_provider_config(AIProvider.BEDROCK)

    # With valid override, validation succeeds
    validate_provider_config(
        AIProvider.BEDROCK,
        screening_override="nova-micro",
        synthesis_override="nova-pro",
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

