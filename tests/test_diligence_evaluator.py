import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.analysis.diligence.evaluator import evaluate_diligence
from app.analysis.diligence.models import (
    DiligenceEvaluation,
    DiligencePillar,
    GapSeverity,
    InformationGap,
)
from app.domain.enums import AIProvider
from app.domain.models import Candidate, Evidence
from app.prompts.diligence import build_diligence_prompt


def _candidate() -> Candidate:
    return Candidate(
        slug="acme",
        name="Acme",
        website="https://acme.example",
        one_liner="AI workflow automation",
        source_url="https://news.example/acme",
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            claim="Customer evidence",
            excerpt="Independent customer report.",
            source_url="https://news.example/acme",
            source_title="Acme report",
            source_type="news",
            trust_tier="open_web",
            verification="third_party",
        )
    ]


def test_diligence_models_use_closed_enums() -> None:
    gap = InformationGap(
        pillar=DiligencePillar.COMMERCIAL_TAM,
        description="Commercial evidence is incomplete.",
        severity=GapSeverity.HIGH,
    )
    assert gap.pillar is DiligencePillar.COMMERCIAL_TAM
    assert gap.severity is GapSeverity.HIGH

    with pytest.raises(ValidationError):
        InformationGap(pillar="invented", description="invalid", severity="urgent")


def test_diligence_prompt_owns_evaluation_and_query_instructions() -> None:
    prompt = build_diligence_prompt(_candidate(), _evidence(), "AI agents", hop=2)
    assert "Return exactly one gap for every diligence pillar" in prompt
    assert "at most one focused follow-up search query for each unresolved gap" in prompt
    assert '"evidence"' in prompt
    assert '"hop": 2' in prompt


def test_evaluate_diligence_validates_structured_model_output(monkeypatch) -> None:
    payload = {
        "gaps": [
            {
                "pillar": pillar.value,
                "description": f"{pillar.value} assessment",
                "severity": "low" if pillar is DiligencePillar.COMMERCIAL_TAM else "medium",
                "resolved": pillar is DiligencePillar.COMMERCIAL_TAM,
                "rationale": "Grounded in supplied evidence.",
                "resolved_by_evidence_id": "ev-001" if pillar is DiligencePillar.COMMERCIAL_TAM else None,
            }
            for pillar in DiligencePillar.core()
        ],
        "followup_queries": [
            {
                "query": "Acme pricing and revenue evidence",
                "pillar": DiligencePillar.UNIT_ECONOMICS.value,
                "rationale": "Resolve the unit economics gap.",
                "hop": 2,
            }
        ],
    }

    def fake_completion(**kwargs):
        assert kwargs["requestMetadata"]["stage"] == "diligence_evaluation"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    monkeypatch.setattr("app.analysis.providers.completion", fake_completion)

    result = evaluate_diligence(
        _candidate(),
        _evidence(),
        "AI agents",
        2,
        provider=AIProvider.BEDROCK,
        model="test-model",
    )

    assert isinstance(result, DiligenceEvaluation)
    assert {gap.pillar for gap in result.gaps} == set(DiligencePillar.core())
    assert result.followup_queries[0].pillar is DiligencePillar.UNIT_ECONOMICS


def test_evaluate_diligence_rejects_duplicate_queries_for_a_pillar(monkeypatch) -> None:
    payload = {
        "gaps": [
            {
                "pillar": pillar.value,
                "description": f"{pillar.value} is unresolved",
                "severity": "high",
                "resolved": False,
                "rationale": "More evidence is required.",
                "resolved_by_evidence_id": None,
            }
            for pillar in DiligencePillar.core()
        ],
        "followup_queries": [
            {
                "query": query,
                "pillar": DiligencePillar.COMMERCIAL_TAM.value,
                "rationale": "Resolve the commercial gap.",
                "hop": 2,
            }
            for query in ("Acme customers", "Acme market size")
        ],
    }

    def fake_completion(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    monkeypatch.setattr("app.analysis.providers.completion", fake_completion)

    with pytest.raises(ValueError, match="one follow-up query per unresolved pillar"):
        evaluate_diligence(
            _candidate(),
            _evidence(),
            "AI agents",
            2,
            provider=AIProvider.BEDROCK,
            model="test-model",
        )
