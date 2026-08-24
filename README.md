# DealGraph

DealGraph is an evidence-first Python CLI that sources recent startups, screens them against a
specific seed thesis, researches the finalists, and writes cited one-page investment memos.

```text
YC + Agent Reach discovery
  -> launch-window eligibility
  -> batched semantic screening
  -> focused finalist research
  -> deterministic score + recommendation
  -> one-page PDF + auditable JSON artifacts
```

The investment thesis is deliberately narrow: pre-seed and seed B2B AI companies that replace a
frequent, expensive SMB workflow, show value quickly, and compound an advantage through
integrations, data, or distribution.

## Run it

Python 3.10+, `uv`, and valid credentials for the selected model provider are required.

```bash
uv sync --extra dev
agent-reach doctor --json
cp .env.example .env
# Fill one supported credential in .env; never commit that file.
uv run --env-file .env dealgraph run \
  --topic "AI agents for SMBs" \
  --limit 10 \
  --output results
```

Bedrock is the default. It accepts an explicit Bedrock bearer token, AWS access-key pair, named AWS
profile, web-identity role pair, or container credential URI. Other providers require their named API
key. DealGraph fails before sourcing when the selected provider is not configured and never logs or
persists credential values.

Useful options:

```bash
uv run --env-file .env dealgraph run --topic "AI infrastructure" --batch W26
uv run --env-file .env dealgraph run --topic "AI agents" --provider openai
uv run --env-file .env dealgraph run --topic "AI agents" --no-deep-diligence
```

`DEALGRAPH_LOOKBACK_DAYS` defaults to 30 and accepts 1–3650. `--limit` is applied after date
selection. A source file may contain YC-style JSON records, structured candidates, or startup URLs.

## What a run writes

Every live run leaves the reviewer-visible evidence trail needed to audit a decision:

```text
results/
├── input.json
├── candidates.json
├── screenings.json
├── shortlist.json
├── gaps.json
├── manifest.json
├── evidence/<finalist>.json
├── analyses/<finalist>.json
└── <finalist>.pdf
```

The JSON files contain public evidence, decisions, safe model provenance, request ID, and failure
gaps. They never contain credentials, authorization headers, prompts, or raw model responses.

A committed example run is available under `examples/ai-agents-smb/`, so reviewers can inspect the
output without credentials or another paid run.

## Case-study requirement coverage

| Requirement | Implementation |
| --- | --- |
| Source 10–20 candidates | One topic command collects 10 by default from enabled public sources, with launch freshness and available team signals. |
| Analyze finalists | Cited Team, Product, Market, Why Now, risks, questions, and five fixed score dimensions are stored in JSON. |
| Clear recommendation | Every finalist receives `Pass`, `Watch`, or `Take a meeting` plus two or three decision-changing proof points. |
| One-page memo | ReportLab produces a structurally single-page PDF with clickable inline citations and a numbered source table. |
| Reviewer trust | Complete sanitized inputs, screening decisions, evidence, gaps, analyses, manifest, and final PDFs are committed. |
| Visible AI process | The commit-linked work log records human scope decisions, RED/GREEN checkpoints, live runs, and independent reviews. |

## Scoring

The synthesizer returns cited 0–10 assessments for five fixed dimensions. Runtime code validates the
dimensions and recomputes the total; the model cannot choose a contradictory total or call.

| Dimension | Weight |
| --- | ---: |
| Workflow pain and frequency | 25% |
| Speed to measurable value | 20% |
| Compounding advantage | 20% |
| Team execution evidence | 15% |
| Market and distribution | 20% |

- 70–100: `Take a meeting`
- 45–69.9: `Watch`
- Below 45: `Pass`

Missing facts remain `Not disclosed`; they do not receive invented credit. Each PDF shows the score
breakdown, company-specific thesis, Team/Product/Market assessment, risks, decision-changing proof
points, and clickable sources on one page.

## Sources and safety

Candidate discovery uses the enabled YC and Agent Reach/Exa channels. Finalist research uses the
enabled company-website source for first-party claims plus three focused searches for team,
traction/funding/freshness, and competition/differentiation. First-party results stay labeled
`CLAIMED`; independent and official evidence ranks above them.

PitchBook, Crunchbase, and LinkedIn are not scraped. Public URL validation, redirect checks, response
limits, fixed subprocess arguments, request-ID propagation, and per-company failure isolation remain
enforced.

## How this was built with AI

The factual, commit-linked work trail is in [docs/AI_WORKLOG.md](docs/AI_WORKLOG.md). Prompt and
architecture decisions are summarized in [docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md). The repository
keeps the RED and GREEN commits rather than presenting only a retrospective narrative.

## Verify

```bash
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
uv pip check
git diff --check
```

Coverage must remain at or above 80%.
