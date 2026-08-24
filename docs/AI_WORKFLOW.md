# DealGraph AI workflow and engineering decisions

This document records the current, verifiable design. It intentionally avoids benchmark, latency,
cost, and reliability claims that are not backed by committed raw results.

## Scope

The take-home asks for triage, not a portfolio-management platform. DealGraph therefore ships as one
Python CLI with no database, queue, vector store, web frontend, or service deployment. A run is a
bounded batch with per-company failure isolation and files as its review surface.

The implemented stages are:

1. Source recent candidates from the enabled public sources.
2. Screen candidates semantically in batches of 20 against the requested topic and fund thesis.
3. Research only the finalists using focused team, traction, and competitive queries.
4. Generate a cited company thesis and five-dimension score breakdown.
5. Validate and recompute the score in Python, then render a one-page PDF.
6. Save the inputs, intermediate decisions, evidence, analyses, failures, and final memos.

## Where AI is used

### Screening

The screening model receives all eligible candidate descriptions in bounded batches. It must return
one decision for every input slug. Runtime validation rejects missing, duplicate, or unexpected slugs.
This stage is high recall: plausible topic fits advance; obvious mismatches do not consume research
and synthesis calls.

The screening prompt is split into persona, guardrails, workflow, and output contract under
`app/prompts/screening/`. Candidate text is serialized as untrusted data, and a Bedrock system message
reinforces that separation.

### Finalist synthesis

The synthesis model receives only public evidence records with stable IDs. It writes concise Team,
Product, Market, Why Now, risk, and decision-changing sections plus a company-specific thesis.
Factual narrative and score rationales require supplied citation IDs. Missing evidence must remain
`Not disclosed`.

The model proposes five 0–10 dimension scores, but it is not authoritative over the result. Python
validates the exact dimension names, fixed weights, score ranges, rationale, and evidence IDs before
recomputing the weighted total and recommendation.

## Thesis and score contract

The thesis targets pre-seed and seed B2B AI companies replacing frequent, expensive SMB workflows
with fast measurable value and a compounding integration, data, or distribution advantage.

```text
workflow_pain          25%
speed_to_value         20%
compounding_advantage  20%
team_execution         15%
market_distribution    20%
```

`score = sum(dimension_score × weight) ÷ 10`

The runtime maps 70+ to `Take a meeting`, 45–69.9 to `Watch`, and lower scores to `Pass`. This rubric
is transparent and reviewable; it is a triage aid, not a claim of investment truth.

## Evidence quality

Candidate discovery is intentionally limited to the source registry. Current default channels are YC
and Agent Reach/Exa. Finalist evidence combines the curated YC profile, direct company pages, and
three focused web searches:

- founder/team background and execution history;
- current traction, customers, launch, and funding evidence;
- competitors, workflow differentiation, and defensibility.

Company-domain search results stay `CLAIMED`, even when returned by a search provider. Official and
independent sources rank above first-party claims, and results are interleaved across domains to avoid
one site creating false confidence.

## Trust boundaries

- External URLs are validated and blocked from private, loopback, link-local, and metadata targets.
- Candidate and website text is treated as untrusted prompt data.
- Provider credentials are required before sourcing and are never printed or stored.
- The Exa adapter uses a fixed subprocess argument list, bounded timeout/output, and a restricted
  environment without API credentials.
- PitchBook, Crunchbase, and LinkedIn remain blocked from scraping.
- One request ID propagates through outbound requests and committed run provenance.
- Failures are isolated by screening batch or finalist and recorded safely in `gaps.json`.

## Why live-only

The final CLI has one supported action: `dealgraph run`. Removing the broken replay command keeps the
exercise honest: a run requires configured credentials and fresh public data. Reviewability comes
from the complete sanitized artifact set written during that live run and the committed example run,
not from a second mode whose inputs were never produced.

## AI-assisted development evidence

The chronological, commit-linked record is [AI_WORKLOG.md](AI_WORKLOG.md). The strongest evidence is
the repository itself:

- RED commits define externally visible behavior before production changes.
- GREEN commits implement the smallest passing behavior.
- Tests preserve prompt contracts, security boundaries, artifact schemas, scoring, and one-page PDFs.
- Independent reviewer and security passes are recorded only after they actually occur.

This document summarizes decisions; it is not a substitute for the work log, tests, diffs, or sample
artifacts.
