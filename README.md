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

## The Problem & Why DealGraph

### 1. The Problem We Are Solving
Early-stage venture deal discovery and triage are flooded with noisy, high-volume inputs. Accelerators, incubator batches (such as YC), and public launch directories produce hundreds of candidate companies simultaneously. Thoroughly reviewing each candidate requires manual research across disparate sources—founder profiles, product pages, pricing models, and independent validation—creating an unsustainable bottleneck for investors, leading to either superficial skimming or missed high-potential deals.

### 2. The Exact Reason
Generic LLM tools and off-the-shelf "AI research agents" fail catastrophically in investment screening due to four structural flaws:
- **Uncorroborated Marketing Claims**: Naive models treat founder claims and website marketing copy as verified facts rather than unvalidated assertions.
- **Metric Hallucination & Inflation**: When financial, pricing, or team data is missing, language models routinely hallucinate estimates or invent plausible traction numbers.
- **Non-Deterministic Scoring**: Asking an LLM to "score this deal from 1 to 10" yields arbitrary, drift-prone numbers that cannot be calibrated or compared across candidates.
- **No Verifiable Audit Trail**: Standard chat tools output freeform text with no structured evidence links, leaving investment committees unable to verify claims against primary sources.

### 3. Why We Are Doing This
DealGraph was built to enforce an **evidence-first, deterministic, and auditable pipeline** for early-stage investment analysis:
- **Thesis-Driven Sourcing**: Systematically filters candidates against an explicit, narrow thesis rather than generic industry tags.
- **Independent Evidence Verification**: Multi-pillar research prioritizes third-party proof over claimed founder copy, penalizing unverified marketing statements.
- **Explicit Missing Information**: Undisclosed details remain strictly `Not disclosed` or `Unknown`—hallucination is blocked at the schema level.
- **Deterministic Python Scoring**: LLMs extract cited facts, but Python code validates evidence IDs, enforces dimension weights, and computes final scores and recommendations (`Take a meeting`, `Watch`, `Pass`).
- **Auditable Artifacts**: Every run generates cited, structurally single-page PDF memos along with complete, reviewer-visible JSON trails for every decision.

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
key. LiteLLM provides the model transport for every provider; DealGraph keeps provider policy, URL
validation, and structured-output prompts in the application. DealGraph fails before sourcing when
the selected provider is not configured and never logs or persists credential values.

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
Deep diligence uses the configured screening model to evaluate the four evidence pillars and return
typed gaps and follow-up queries; Python validates that structured result before any search runs.
If independent search is rate-limited, the run stops repeated quota-bound calls, completes from the
available evidence, and records a sanitized `Research availability` gap instead of hiding the outage.

A committed example run is available under `examples/ai-agents-smb/`, so reviewers can inspect the
output without credentials or another paid run.

## Architecture diagrams

The documentation includes two complementary views of the live implementation:

| Diagram | What it answers |
| --- | --- |
| [High-level system architecture](doc/system-architecture.html) | How the CLI, pipeline, sourcing, screening, diligence, scoring, providers, and artifacts fit together |
| [Technical pipeline data flow](doc/pipeline-data-flow.html) | How payloads, request identity, provider calls, trust controls, failure isolation, and atomic outputs move through one run |

The [technical guide](doc/README.md) maps each diagram back to its owning Python modules and runtime
contract.

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

Displayed confidence is deterministic evidence coverage, not a model self-rating: it rewards
verified/trusted evidence, an independent source, distinct domains, source diversity, corpus depth,
and extracted financial facts. First-party claims alone cannot create high confidence.

## Sources and safety

Candidate discovery uses the enabled YC and Agent Reach/Exa channels. Finalist research uses the
enabled company-website source for first-party claims, then lets the diligence evaluation prompt
return structured follow-up gaps and searches per pillar. First-party results stay labeled
`CLAIMED`; independent and official evidence ranks above them.

Agent Reach discovery may retain PitchBook, Crunchbase, and LinkedIn company profiles as attributed
directory sources. They remain unverified directory claims and are never substituted for an official
company website. Public URL validation, redirect checks, response limits, fixed subprocess arguments,
request-ID propagation, and per-company failure isolation remain enforced.

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
