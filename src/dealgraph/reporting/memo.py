"""Render the one artifact an investment partner should need to read."""

from dealgraph.domain.models import Analysis, Candidate, Evidence


def render_memo(candidate: Candidate, analysis: Analysis, evidence: list[Evidence]) -> str:
    scores = "\n".join(
        f"| {item.name.replace('_', ' ').title()} | {item.score:.0f}/100 | {item.weight}% | {item.rationale} [{', '.join(item.evidence_ids)}] |"
        for item in analysis.dimensions
    )
    risks = "\n".join(f"- {item}" for item in analysis.risks)
    questions = "\n".join(f"- {item}" for item in analysis.open_questions)
    changes = "\n".join(f"- {item}" for item in analysis.changes_mind)
    sources = "\n".join(
        f"- [{item.id}] [{item.source_title}]({item.source_url}) — {item.verification}"
        for item in evidence
    )
    financials = "\n".join(
        f"- **{name.title()}:** {value or 'Unknown'}"
        for name, value in analysis.financials.model_dump(exclude={"evidence_ids"}).items()
    )
    return f"""# {candidate.name} — Investment Memo

**Decision:** {analysis.recommendation}
**Score:** {analysis.score:.1f}/100 · **Evidence confidence:** {analysis.confidence:.0%}
**Website:** [{candidate.website}]({candidate.website})
**Analysis mode:** `{analysis.analysis_mode}`

## 60-second view

{analysis.summary}

## Team

{analysis.team}

## Product

{analysis.product}

## Market and why now

{analysis.market}

{analysis.why_now}

## Public financial signals

{financials}

## Thesis score

| Dimension | Score | Weight | Evidence-grounded rationale |
|---|---:|---:|---|
{scores}

## Risks and open questions

{risks}
{questions}

## What would change our mind

{changes}

## Sources

{sources}
"""
