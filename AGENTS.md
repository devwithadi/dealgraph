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

## Mandatory ECC harness

For every non-trivial change, use the ECC flow: inspect the complete caller path, plan, write and run a RED test, implement the minimum GREEN change, refactor only proven duplication, run code review, run security review when trust boundaries are touched, and complete the verification gates below. Use the ECC planner/architect, TDD guide, code reviewer, and security reviewer roles when their triggers apply.

## Mandatory Ponytail

Read and apply the `$ponytail` skill before planning or implementing code. Search before writing, prefer the standard library and installed dependencies, and ship the smallest design that satisfies the explicit requirement. Do not add one-implementation interfaces, factories, repositories, compatibility layers, or speculative modules. Correctness, security controls, and explicit user requirements must never be simplified away. Ponytail stays active unless the user says “stop Ponytail.”

## Architecture

- `app/cli/`: the only supported user interface and top-level error boundary.
- `app/core/`: logging, `X-Kong-Request-ID` context, and application errors.
- `app/domain/`: immutable Pydantic contracts and closed business enums.
- `app/sourcing/`: source registry, candidate selection, SSRF-safe fetching, and evidence adapters.
- `app/analysis/`: deterministic scoring and optional OpenAI narrative generation.
- `app/prompts/`: modular persona, workflow, and structured-output prompts.
- `app/reporting/`: Markdown memo rendering.
- `app/pipeline/`: orchestration, failure isolation, and run artifacts.
- `tests/fixtures/`: replayable inputs; tests must not require live network access.

Dependencies point inward: CLI → pipeline → domain services → domain/core. Lower layers never import pipeline or CLI. Import concrete modules instead of hiding dependencies behind broad package re-exports.

## Required behavior

- Write tests first for behavior changes and keep the full suite green.
- Keep stdout concise. Human summaries or `--json` go to stdout; logs and errors go to stderr.
- Propagate one validated request ID through every outbound request, manifest, and run summary. Use `X-Kong-Request-ID` for HTTP and Bedrock request metadata for Converse.
- Bedrock is the default narrative provider. Use Boto3 `Converse`, preserve request metadata, and create clients lazily so offline mode never performs AWS credential or metadata discovery.
- OpenAI-compatible endpoints come only from validated public HTTPS `OPENAI_BASE_URL` configuration on port 443; never log or persist API keys.
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
