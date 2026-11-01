from __future__ import annotations

from pydantic import Field

from app.analysis.diligence.constants import DILIGENCE
from app.domain.enums import ValueEnum
from app.domain.models import Candidate, Evidence, FrozenModel


class DiligencePillar(ValueEnum):
    COMMERCIAL_TAM = "Commercial / TAM"
    UNIT_ECONOMICS = "Unit Economics"
    TECH_IP = "Tech / IP Defensibility"
    RISK_ESG = "Risk / ESG"
    RESEARCH_AVAILABILITY = "Research availability"

    @classmethod
    def core(cls) -> tuple[DiligencePillar, ...]:
        return (
            cls.COMMERCIAL_TAM,
            cls.UNIT_ECONOMICS,
            cls.TECH_IP,
            cls.RISK_ESG,
        )


class GapSeverity(ValueEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SearchQuery(FrozenModel):
    query: str
    pillar: DiligencePillar = DiligencePillar.COMMERCIAL_TAM
    rationale: str = ""
    hop: int = DILIGENCE.initial_hop
    executed: bool = False
    results_count: int = DILIGENCE.empty_results_count


class InformationGap(FrozenModel):
    pillar: DiligencePillar
    description: str
    severity: GapSeverity = GapSeverity.MEDIUM
    resolved: bool = False
    rationale: str = ""
    resolved_by_evidence_id: str | None = None


class DiligencePlan(FrozenModel):
    candidate_slug: str
    candidate_name: str
    topic: str
    queries: list[SearchQuery] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    pillars: list[DiligencePillar] = Field(default_factory=lambda: list(DiligencePillar.core()))


class DiligenceEvaluation(FrozenModel):
    gaps: list[InformationGap]
    followup_queries: list[SearchQuery] = Field(default_factory=list)


class DiligenceState(FrozenModel):
    candidate: Candidate
    topic: str
    current_hop: int = DILIGENCE.unstarted_hop
    max_hops: int = DILIGENCE.default_max_hops
    plan: DiligencePlan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[InformationGap] = Field(default_factory=list)
    queries_executed: list[SearchQuery] = Field(default_factory=list)
    is_complete: bool = False
    notes: list[str] = Field(default_factory=list)
