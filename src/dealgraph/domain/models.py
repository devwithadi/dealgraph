"""Small immutable contracts shared by the pipeline."""

from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field

from dealgraph.domain.enums import AnalysisMode, Recommendation


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Candidate(FrozenModel):
    slug: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    name: str
    website: str
    one_liner: str
    description: str = ""
    batch: str = ""
    industry: str = ""
    tags: list[str] = Field(default_factory=list)
    team_size: int | None = None
    launched_at: datetime | None = None
    is_hiring: bool = False
    source_url: str


class Evidence(FrozenModel):
    id: str
    claim: str
    excerpt: str
    source_url: str
    source_title: str
    source_type: str
    trust_tier: str
    verification: str
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DimensionScore(FrozenModel):
    name: str
    score: float = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class Financials(FrozenModel):
    revenue: str | None = None
    burn: str | None = None
    runway: str | None = None
    funding: str | None = None
    pricing: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class Analysis(FrozenModel):
    company: str
    thesis: str
    summary: str
    team: str
    product: str
    market: str
    why_now: str
    financials: Financials
    risks: list[str]
    open_questions: list[str]
    changes_mind: list[str]
    dimensions: list[DimensionScore]
    score: float
    confidence: float = Field(ge=0, le=1)
    recommendation: Recommendation
    analysis_mode: AnalysisMode


class RunSummary(FrozenModel):
    run_id: str
    request_id: str
    output: str
    candidates: int
    succeeded: int
    failed: int
