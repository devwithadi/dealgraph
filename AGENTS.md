# DealGraph agent guide

DealGraph is a small Python CLI that turns public startup data into cited seed-investment analyses and Markdown memos. Preserve its evidence-first behavior and keep the implementation understandable enough to review as a case study.

## Start here

```bash
uv sync --extra dev
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
uv run dealgraph run --topic "AI agents for SMBs" --limit 10
```

Python 3.10+ and `uv` are expected. Keep total coverage at or above 80%.

## Architecture

- `app/cli.py`: the only supported user interface and top-level error boundary.
- `app/pipeline.py`: orchestration, failure isolation, and run artifacts.
- `app/sources.py`: YC/Hacker News sourcing, robots handling, SSRF policy, and HTML extraction.
- `app/analysis.py`: deterministic scoring and optional OpenAI narrative generation.
- `app/logging.py`: logging configuration and `X-Kong-Request-ID` context.
- `app/errors.py`: expected application errors and safe CLI reporting.
- `app/models.py`: immutable Pydantic data contracts.
- `tests/fixtures/`: replayable inputs; tests must not require live network access.

## Required behavior

- Write tests first for behavior changes and keep the full suite green.
- Keep stdout concise. Human summaries or `--json` go to stdout; logs and errors go to stderr.
- Propagate one validated `X-Kong-Request-ID` through every outbound request, manifest, and run summary.
- `--offline` must perform zero network requests, including OpenAI.
- Preserve per-company failure isolation and return nonzero when any company fails.
- Missing financial or team facts stay `null` or `Unknown`; never fabricate evidence.

## Source and security rules

- Only use sources enabled in `SOURCE_REGISTRY`.
- Never scrape PitchBook, Crunchbase, or LinkedIn. PitchBook requires a separately licensed API and permitted use.
- Preserve public-IP validation on every redirect, robots.txt checks, response-size limits, and safe artifact filenames.
- Never log API keys, authorization headers, prompts, response bodies, or other secrets.
- Validate all external data at its boundary. Keep error messages safe and actionable.

## Change discipline

- Prefer standard-library or existing dependencies over new packages.
- Keep functions small and models immutable; avoid speculative abstractions.
- Do not silently change the scoring rubric, source trust policy, or recommendation thresholds.
- Update `README.md` when CLI commands or observable behavior change.
- Before handoff, run tests with coverage, `uv pip check`, `git diff --check`, and inspect `git status`.

The primary command is `dealgraph`; `ida` remains a compatibility alias for existing scripts.
