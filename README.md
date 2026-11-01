# DealGraph

A small, replayable CLI that finds YC startups, collects public evidence, scores each company against a fixed seed thesis, and writes cited investment memos.

## Quick start

```bash
uv sync --extra dev
uv run dealgraph run --topic "AI agents for SMBs" --limit 10 --output data/runs/latest
```

Normal output stays intentionally short:

```text
Completed 10/10 companies.
Memos: /absolute/path/data/runs/latest/memos
Request ID: req-5ae470bb25d84a87
```

Open `data/runs/latest/memos/` for the finished memos. No API key is required. If `OPENAI_API_KEY` is set, OpenAI writes the narrative sections; otherwise the complete run uses the labelled deterministic fallback.

## Common commands

Limit the search to a YC batch:

```bash
uv run dealgraph run --topic "AI agents for SMBs" --batch W25 --limit 10
```

Replay a saved source file without website, Hacker News, or OpenAI requests:

```bash
uv run dealgraph run \
  --topic "AI agents for SMBs" \
  --batch W25 \
  --limit 1 \
  --source-file tests/fixtures/yc.json \
  --offline \
  --output data/runs/replay
```

`--offline` requires `--source-file`; DealGraph fails before making any request when the local input is missing.

Use `--json` for automation and `--verbose` for operational logs. JSON and summaries go to stdout; logs and errors go to stderr, so redirects remain safe:

```bash
uv run dealgraph run --topic "AI agents" --json > run-summary.json
uv run dealgraph run --topic "AI agents" --verbose
```

## Pipeline

```text
YC public JSON → topic/batch filter → company website + Hacker News evidence
               → deterministic thesis score → optional OpenAI narrative
               → cited JSON analysis + Markdown memo
```

The code follows the same domain boundaries:

```text
src/dealgraph/
├── cli/          command parsing and top-level error boundary
├── core/         logging, request tracking, and application errors
├── domain/       immutable models and closed business enums
├── sourcing/     registry, candidates, fetch policy, and evidence adapters
├── analysis/     scoring and evidence-backed narrative analysis
├── reporting/    Markdown memo rendering
└── pipeline/     end-to-end orchestration and run artifacts
```

Every run creates:

```text
data/runs/latest/
├── input.json
├── candidates.json
├── manifest.json
├── evidence/<company>.json
├── analyses/<company>.json
└── memos/<company>.md
```

`manifest.json` records the sources, analysis mode, successes, failures, evidence gaps, and request ID. A failure enriching one company does not stop the rest of the batch.

## Logging and request tracking

One request ID is generated per run and attached to every outbound call as `X-Kong-Request-ID`, including YC, robots.txt, company pages, Hacker News, and OpenAI. Use `--request-id <trusted-id>` to continue an upstream trace. IDs are restricted to 1–128 safe characters to prevent header and log injection.

Default mode prints only the result, memo directory, and request ID. `--verbose` adds run and candidate lifecycle logs without response bodies, prompts, authorization headers, or API keys. Expected failures return a concise message and exit code; unexpected tracebacks appear only in verbose mode.

The internally created HTTP client reuses connections, limits its pool, applies timeouts, and retries connection failures twice. Runs remain sequential because the assignment batch is only 1–20 companies and predictable source load is more valuable than added concurrency.

## Scoring and missing data

The thesis targets pre-seed and seed B2B AI companies that replace frequent, expensive SMB workflows and compound an advantage through integrations, data, or distribution.

| Dimension | Weight |
|---|---:|
| Pain and ROI | 25% |
| Differentiation | 20% |
| Team | 20% |
| Distribution | 15% |
| Market | 10% |
| Freshness/traction | 10% |

- `Take a meeting`: score ≥75 and evidence confidence ≥65%
- `Watch`: score ≥60, or high score with low confidence
- `Pass`: score <60

Revenue, burn, runway, funding, pricing, or team facts remain `null`/`Unknown` unless the evidence supports them. The model is never asked to invent missing financial data.

## Source policy

Enabled sources are YC's public community JSON feed, public company websites, and Hacker News. URLs are checked against blocked vendors and non-public IP ranges on every redirect. Robots rules are respected and responses are capped at 2 MB.

PitchBook, Crunchbase, and LinkedIn scraping are disabled. PitchBook should only be integrated through a licensed API contract that permits the intended use.

## Verify

```bash
uv run pytest
uv run pytest --cov=dealgraph --cov-report=term-missing
```

The committed `data/runs/demo/` directory provides reviewable output without external calls. See [docs/AI_WORKLOG.md](docs/AI_WORKLOG.md) for the implementation trail and deliberate scope cuts.
