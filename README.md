# Investment Decision Assistant

A deliberately small, replayable pipeline that sources YC startups, collects public evidence, scores them against a fixed thesis, and writes one-page investment memos.

## Run it

```bash
uv sync --extra dev
uv run ida run \
  --topic "AI agents for SMBs" \
  --limit 10 \
  --output data/runs/latest
```

Use `--batch W25` to restrict a YC batch. Set `OPENAI_API_KEY` for an LLM-written narrative; without it, the complete pipeline still runs with an explicitly labelled deterministic fallback.

Replay without network access:

```bash
uv run ida run \
  --topic "AI agents for SMBs" \
  --batch W25 \
  --limit 1 \
  --source-file tests/fixtures/yc.json \
  --offline \
  --output data/runs/replay
```

## What it does

```text
YC public JSON → topic/batch filter → company website + Hacker News evidence
               → deterministic thesis score → optional OpenAI narrative
               → cited JSON analysis + Markdown memo
```

Each run writes `input.json`, `candidates.json`, `manifest.json`, and per-company files under `evidence/`, `analyses/`, and `memos/`. The committed `data/runs/demo` directory lets reviewers inspect output without rerunning external calls.

## Thesis and recommendation

The thesis targets pre-seed/seed B2B AI companies that replace frequent, expensive SMB workflows and compound an advantage through integrations, data, or distribution.

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

Unknown revenue, burn, runway, funding, or team data remains `null`/`Unknown`; the model is never asked to invent it.

## Source policy

Enabled sources are YC's community JSON feed, public company websites, and Hacker News. URLs are checked against blocked vendors and non-public IP ranges, including every redirect. Robots rules are respected and responses are capped at 2 MB.

PitchBook, Crunchbase, and LinkedIn scraping are disabled. PitchBook can only be added through a separately licensed API contract that permits the intended AI use.

## Verify

```bash
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
```

See [docs/AI_WORKLOG.md](docs/AI_WORKLOG.md) for the real implementation trail and deliberate scope cuts.
