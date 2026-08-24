from dataclasses import replace

import httpx
import pytest

from app.domain.enums import AIProvider
from app.pipeline.service import Pipeline
from app.prompts.screening import build_discovery_prompt
from app.sourcing.constants import AGENT_REACH, BLOCKED_HOSTS
from app.sourcing.policy import BLOCKED_HOSTS as POLICY_BLOCKED_HOSTS


def test_agent_reach_limits_have_one_immutable_source() -> None:
    assert BLOCKED_HOSTS == frozenset()
    assert POLICY_BLOCKED_HOSTS is BLOCKED_HOSTS
    assert AGENT_REACH.subprocess_timeout_seconds == 35
    assert AGENT_REACH.mcporter_timeout_milliseconds == 30_000
    assert AGENT_REACH.max_output_bytes == 200_000
    assert AGENT_REACH.discovery_model_max_tokens == 2_000
    assert AGENT_REACH.default_batch == "Agent Reach Discovery"
    assert AGENT_REACH.default_tags == ("Agent Reach", "Discovery", "AI")
    assert AGENT_REACH.directory_hosts == ("pitchbook.com", "crunchbase.com", "linkedin.com")
    assert AGENT_REACH.directory_site_filters == (
        "site:pitchbook.com",
        "site:crunchbase.com",
        "site:linkedin.com/company",
    )
    assert AGENT_REACH.directory_labels_text == "PitchBook, Crunchbase, and LinkedIn"


def test_discovery_prompt_uses_constant_directory_labels() -> None:
    prompt = build_discovery_prompt("{}", "AI agents")

    assert AGENT_REACH.directory_labels_text in prompt
    assert "PitchBook, Crunchbase, and LinkedIn profile URLs" in prompt


def test_discovery_uses_the_agent_reach_model_token_constant(monkeypatch, tmp_path) -> None:
    configured = replace(AGENT_REACH, discovery_model_max_tokens=123)
    captured: dict[str, object] = {}

    class StopAfterDiscovery(Exception):
        pass

    def fake_model_json(*_args, **kwargs):
        captured.update(kwargs)
        return {"candidates": []}

    def fake_discover(**kwargs):
        kwargs["structured_output"]("raw Agent Reach result")
        raise StopAfterDiscovery

    monkeypatch.setattr("app.pipeline.service.AGENT_REACH", configured)
    monkeypatch.setattr("app.pipeline.service.model_json", fake_model_json)
    monkeypatch.setattr("app.pipeline.service.discover_candidates", fake_discover)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-only")

    with pytest.raises(StopAfterDiscovery):
        Pipeline(
            client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))),
        ).run(
            topic="AI agents",
            batch=None,
            limit=1,
            output=tmp_path,
            provider=AIProvider.BEDROCK,
        )

    assert captured["max_tokens"] == 123
