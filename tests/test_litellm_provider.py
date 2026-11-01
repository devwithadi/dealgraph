from types import SimpleNamespace

import pytest

import app.analysis.providers as providers
from app.core.errors import AppError
from app.core.logging import bind_request_id
from app.domain.enums import AIProvider


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_bedrock_model_json_delegates_to_litellm_with_request_metadata(monkeypatch) -> None:
    calls: list[dict] = []
    bind_request_id("req-litellm")

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _response('{"status": "ok"}')

    monkeypatch.setattr(providers, "completion", fake_completion)

    result = providers.model_json(
        "Evaluate candidate",
        provider=AIProvider.BEDROCK,
        model="amazon.nova-lite-v1:0",
        max_tokens=500,
        stage="screening",
    )

    assert result == {"status": "ok"}
    assert calls == [
        {
            "model": "bedrock/amazon.nova-lite-v1:0",
            "messages": [
                {"role": "system", "content": providers.BEDROCK_SYSTEM_GUARD},
                {"role": "user", "content": "Evaluate candidate"},
            ],
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
            "drop_params": True,
            "requestMetadata": {
                "application": "dealgraph",
                "request_id": "req-litellm",
                "stage": "screening",
            },
            "num_retries": 0,
            "timeout": providers.PROVIDER_RUNTIME.request_timeout_seconds,
        }
    ]


@pytest.mark.parametrize(
    ("provider", "key_env", "model", "expected_model"),
    [
        (AIProvider.OPENAI, "OPENAI_API_KEY", "gpt-4.1-mini", "openai/gpt-4.1-mini"),
        (
            AIProvider.OPENROUTER,
            "OPENROUTER_API_KEY",
            "qwen/qwen-2.5-72b-instruct",
            "openrouter/qwen/qwen-2.5-72b-instruct",
        ),
        (AIProvider.DEEPSEEK, "DEEPSEEK_API_KEY", "deepseek-chat", "deepseek/deepseek-chat"),
        (AIProvider.DASHSCOPE, "DASHSCOPE_API_KEY", "qwen-plus", "dashscope/qwen-plus"),
        (AIProvider.ZHIPU, "ZHIPU_API_KEY", "glm-4-plus", "zai/glm-4-plus"),
    ],
)
def test_remote_provider_model_json_delegates_to_litellm(
    monkeypatch,
    provider: AIProvider,
    key_env: str,
    model: str,
    expected_model: str,
) -> None:
    calls: list[dict] = []
    monkeypatch.setenv(key_env, "secret-key")

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _response("```json\n{\"status\": \"ok\"}\n```")

    monkeypatch.setattr(providers, "completion", fake_completion)

    result = providers.model_json(
        "Evaluate candidate",
        provider=provider,
        model=model,
        max_tokens=400,
        stage="synthesis",
    )

    assert result == {"status": "ok"}
    call = calls[0]
    assert call["model"] == expected_model
    assert call["api_key"] == "secret-key"
    assert call["api_base"] == providers._provider_url(provider)
    assert call["num_retries"] == 0
    assert "requestMetadata" not in call


def test_litellm_errors_are_sanitized(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    def fail(**_kwargs):
        raise RuntimeError("secret-key provider response body")

    monkeypatch.setattr(providers, "completion", fail)

    with pytest.raises(AppError, match="^OpenAI synthesis unavailable$") as caught:
        providers.model_json(
            "prompt",
            provider=AIProvider.OPENAI,
            model="gpt-4.1",
            max_tokens=100,
            stage="synthesis",
        )

    assert "secret-key" not in str(caught.value)
