# AI-assisted implementation log

This is a factual work log, not a retrospective written to sound impressive.

## 2026-08-20 — repository audit

- Human request: assess and then implement the Emergence investment-pipeline case study.
- AI found that the starting repository could not collect tests, used fictional `.example.com` YC records, manufactured evidence without HTTP requests, and combined incompatible model/service versions.
- Human decisions during discussion: use public trusted sources, add a source allowlist, collect financial signals without inventing private financials, and do not scrape PitchBook without licensed API permission.

## 2026-08-20 — scope decision

- Used the requested `ponytail` workflow to prefer the smallest working path.
- Kept: one CLI, YC sourcing, public-site evidence, HN traction, deterministic scoring, optional OpenAI narrative, local JSON/Markdown artifacts.
- Removed: FastAPI, provider factories, fake companies, queues, database, frontend, browser automation, Gemini adapter, PitchBook/Crunchbase/LinkedIn scraping.
- Deferred SEC Form D: private-company entity resolution would consume much of the 6–8 hour exercise for inconsistent coverage. Missing funding remains explicit instead.

## 2026-08-20 — TDD evidence

- `f901de6`: RED — tests defined the offline CLI, sourcing, scoring, citations, SSRF checks, and artifact contract; failure was missing pipeline modules.
- `f37082e`: GREEN — minimal source-to-memo implementation; 11 tests passed.
- `6a1df56`: RED — tightened source policy, financial gaps, redirect/robots, citation, and analysis-shape requirements.
- `60aafa8`: GREEN — implemented the stricter policy; 15 tests passed.
- `09931d6` → `4835a96`: RED/GREEN — stopped multiple pages from one company domain inflating evidence confidence; 16 tests passed.

## 2026-08-20 — independent review

- Code/security reviewer agents found that the HN query could select a high-scoring but unrelated result. The matcher now requires the startup domain (or company-name fallback when no domain exists).
- Reviewers added direct CLI, live-source-path, and HN entity-matching coverage.
- Final local result: 20 tests, 87%+ coverage, compatible dependencies, and a live 10-company run with 10 successes.

AI produced the implementation and tests. The scoring thesis, trust policy, and final memo quality should still be challenged by a human investment partner; deterministic fallback scoring is intentionally transparent rather than presented as investment truth.

## 2026-08-21 — observability and CLI reliability

- `ecba13b`: RED — defined concise CLI, centralized error, and request propagation behavior.
- `550094e`: RED — added request-ID injection and verbose lifecycle requirements.
- `fc8181e` and `e9b304b`: RED — covered safe artifact names, partial failures, reserved headers, OpenAI tracking, and fully offline analysis.
- `22a8f28`: GREEN — added standard-library logging and error modules, one validated request ID across logs/artifacts/outbound requests, concise default output, JSON/verbose modes, connection retries, pool limits, and safe source-load failures. Final verification: 34 tests and 89.94% coverage.

## 2026-08-21 — DealGraph modular package

- Applied the requested ECC TDD flow and Ponytail constraint: domain boundaries without repositories, factories, interfaces, or new dependencies.
- `18bd65d`: RED — tests defined the `src/dealgraph` package, domain imports, central enum values, and agent-workflow contract.
- `d4cc528`: GREEN — moved the working application into `core`, `domain`, `sourcing`, `analysis`, `reporting`, `pipeline`, and `cli` packages without changing external behavior.
- `24c083a`: RED — proved offline mode without a local source could still attempt YC network access.
- `de7dacb`: GREEN/refactor — split sourcing into registry/candidates/policy/evidence and analysis into scoring/service, then made offline mode fail before all network access. Final verification: 38 tests, 90.62% coverage, and successful wheel/source builds.

## 2026-08-21 — analysis providers

- Verified the current Bedrock Converse request/response contract against official AWS documentation before implementation.
- `7bafa70`: RED — tests defined Bedrock-default selection, Converse metadata, manifest provenance, and a configurable OpenAI base URL.
- `227622a`: GREEN — added direct Bedrock/OpenAI/deterministic dispatch, Bedrock request metadata, HTTPS OpenAI base URL validation, and Boto3 support without provider factories.
- `ddc8bc4` and `2aef38a`: RED — covered private OpenAI gateway rejection, fail-fast configuration, offline AWS-client isolation, and mixed-provider provenance.
- `1cf902a`: GREEN — centralized public target validation, blocked private/custom-port credential exfiltration, and recorded mixed analysis modes accurately. Final verification: 43 tests, 90.88% coverage, compatible dependencies, and successful wheel/source builds.
