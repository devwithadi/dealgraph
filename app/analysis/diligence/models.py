from __future__ import annotations

from pydantic import Field

from app.domain.enums import ValueEnum
from app.domain.models import Candidate, Evidence, FrozenModel


class DiligencePillar(ValueEnum):
    COMMERCIAL_TAM = "Commercial / TAM"
    UNIT_ECONOMICS = "Unit Economics"
    TECH_IP = "Tech / IP Defensibility"
    RISK_ESG = "Risk / ESG"


class SearchQuery(FrozenModel):
    query: str
    pillar: str = DiligencePillar.COMMERCIAL_TAM.value
    rationale: str = ""
    hop: int = 1
    executed: bool = False
    results_count: int = 0


class InformationGap(FrozenModel):
    pillar: str
    description: str
    severity: str = "medium"
    resolved: bool = False
    rationale: str = ""
    resolved_by_evidence_id: str | None = None


class DiligencePlan(FrozenModel):
    candidate_slug: str
    candidate_name: str
    topic: str
    queries: list[SearchQuery] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    pillars: list[str] = Field(
        default_factory=lambda: [
            DiligencePillar.COMMERCIAL_TAM.value,
            DiligencePillar.UNIT_ECONOMICS.value,
            DiligencePillar.TECH_IP.value,
            DiligencePillar.RISK_ESG.value,
        ]
    )


class DiligenceState(FrozenModel):
    candidate: Candidate
    topic: str
    current_hop: int = 0
    max_hops: int = 2
    plan: DiligencePlan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[InformationGap] = Field(default_factory=list)
    queries_executed: list[SearchQuery] = Field(default_factory=list)
    is_complete: bool = False
    notes: list[str] = Field(default_factory=list)
