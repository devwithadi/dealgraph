from __future__ import annotations

import pytest

from app.analysis.providers import (
    PROVIDER_CONFIGS,
    model_for,
    resolve_model_id,
    screening_model_for,
    validate_provider_config,
)
from app.core.errors import AppError
from app.domain.enums import AIProvider


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


def test_openai_model_json_missing_key_error(monkeypatch) -> None:
    from app.analysis.providers import model_json

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AppError, match="OPENAI_API_KEY is required"):
        model_json(
            "test prompt",
            provider=AIProvider.OPENAI,
            model="gpt-4.1-mini",
            max_tokens=500,
            stage="synthesis",
        )
