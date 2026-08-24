# AI-assisted implementation log

This is a factual work log tied to repository evidence, not a retrospective written to sound
impressive. AI produced substantial implementation and tests; human prompts set scope and accepted
or rejected trade-offs.

## 2026-08-20 — repository audit and scope

- Human request: assess and implement the Emergence investment-pipeline case study.
- AI found that the starting repository could not collect tests, used fictional `.example.com` YC
  records, manufactured evidence without HTTP requests, and mixed incompatible service versions.
- Human decisions: public trusted sources only, explicit source allowlist, no invented financials,
  and no PitchBook scraping without licensed access.
- Ponytail scoping kept one CLI and removed FastAPI, queues, database, frontend, browser automation,
  provider factories, fake companies, and forbidden scrapers.

## 2026-08-20 — first TDD implementation

- `f901de6`: RED — tests defined sourcing, scoring, citations, SSRF checks, artifacts, and CLI behavior.
- `f37082e`: GREEN — minimal source-to-memo implementation; 11 tests passed.
- `6a1df56`: RED — tightened source policy, missing-financial, redirects/robots, and analysis shape.
- `60aafa8`: GREEN — implemented the stricter policy; 15 tests passed.
- `09931d6` → `4835a96`: RED/GREEN — prevented repeated pages from one company domain from
  inflating evidence confidence; 16 tests passed.

## 2026-08-20 — independent review

- Reviewer agents found that Hacker News selection could choose a high-scoring but unrelated result.
- Entity matching was changed to require the startup domain, with a company-name fallback only when
  no domain exists.
- Direct CLI, live source, and HN entity-matching tests were added.

## 2026-08-21 — observability and package boundaries

- `ecba13b`, `550094e`, `fc8181e`, `e9b304b`: RED — concise CLI, centralized errors, request IDs,
  safe artifact names, provider tracking, and failure behavior.
- `22a8f28`: GREEN — one validated request ID across logs, artifacts, and outbound calls; retries,
  connection limits, JSON/verbose output, and safe source errors.
- `18bd65d`: RED — defined domain boundaries and import rules.
- `d4cc528`, `de7dacb`: GREEN/refactor — split core, domain, sourcing, analysis, reporting, pipeline,
  and CLI without repositories, factories, or new infrastructure.

## 2026-08-21 — model providers and security

- AWS Bedrock Converse behavior was checked against official documentation before implementation.
- `7bafa70`: RED — Bedrock default, request metadata, provenance, and configurable OpenAI endpoint.
- `227622a`: GREEN — direct Bedrock/OpenAI dispatch and HTTPS endpoint validation.
- `ddc8bc4`, `2aef38a`: RED — private gateway rejection, fail-fast configuration, and provenance.
- `1cf902a`: GREEN — centralized public-target validation and safe model provenance.

## 2026-08-24 — submission audit

- Human supplied the original case-study rubric and asked for a real run and likely score.
- AI ran 10 live candidates: 3 finalists produced 3 PDFs with no runtime failures.
- Visual review found that memos were three pages, source tables left mostly blank final pages,
  scorecard text clipped, citation arrows rendered as squares, and every company displayed the same
  global thesis.
- Repository review found no committed outputs, a removed work log, a replay command whose required
  JSON was never produced, unverifiable benchmark claims, and eight local commits not on the remote.
- Initial evidence-backed estimate was 61/100 despite strong tests and architecture.

## 2026-08-24 — submission-focused RED/GREEN cycle

- Human decision: remove offline/replay and require configured credentials for live data.
- Planner recommendation: compensate with complete sanitized run artifacts, company-specific thesis,
  runtime-computed scoring, focused research, and one-page memos.
- `59f6723`: RED — six failures proved replay/offline exposure, missing artifacts, thesis overwrite,
  absent deterministic scoring, and multi-page PDFs.
- `16ccda5`: RED — proved candidate discovery ignored the enabled source registry.
- `f16a0c8`: GREEN — live-only CLI; explicit credential gate; atomic artifacts; five validated score
  dimensions; runtime score/recommendation; focused three-query research; truthful evidence ranking;
  concise synthesis; and guaranteed one-page PDFs.
- GREEN verification at the checkpoint: 151 tests passed.

## 2026-08-24 — live verification refresh

- Ran `uv run --env-file .env dealgraph run --topic "AI agents for SMBs" --limit 10 --output /tmp/dealgraph-live-20260824`.
- Result: 10 candidates screened, 2 finalists (`Covera`, `Gini`), 2 PDFs, 0 runtime failures.
- Review notes from the generated artifacts:
  - both PDFs rendered as single-page Quick Look previews;
  - `Covera` remained evidence-light on independent traction and financials, and `gaps.json` records that explicitly;
  - `Gini` produced the stronger reviewer story because public pricing, team, docs, and security pages were all captured.
- Synced that live run into `examples/ai-agents-smb/` so the repository contains fresh reviewer-readable output.

## 2026-08-24 — final adversarial review

- An independent code-review agent found that a model response could omit the five dimensions and
  fall back to its own unverified total and recommendation.
- `6a48539`: RED — proved that incomplete synthesis output was still accepted.
- GREEN — synthesis now rejects missing dimensions; the runtime always derives the 0–100 total and
  recommendation from the fixed weights. OpenAI example model names were also corrected to real
  defaults.
- Final checkpoint: 152 tests passed after deleting the retired fallback normalizers and adding
  public-IP validation for search-result citations. Scraped token-like strings are redacted before
  they can reach artifacts. Build, dependency, coverage, diff, artifact-secret, and PDF
  layout/link checks were run before handoff.
- The exact hardened commit then completed a fresh live smoke run: 10/10 candidates screened,
  3 finalists (`Covera`, `Gini`, and `Lantern AI`), 3/3 one-page PDFs, and zero failures. That run
  replaced the earlier two-company example under `examples/ai-agents-smb/`.

## Human follow-up still required

- Record and submit the requested five-minute walkthrough video showing one company from candidate
  record through evidence, score, and PDF.
- Review the committed example memos as an investor. Automated validation can enforce citations and
  scoring consistency, but it cannot decide whether the investment judgment is genuinely insightful.

## 2026-08-24 — final requirement and PDF audit

- Re-rendered all three committed PDFs and inspected the full page images. Each remained one page,
  with no overlap, clipping, broken glyphs, or unreadable text; annotation inspection found only
  public HTTP(S) targets.
- `beba75f` → `1bc93bb`: RED/GREEN — compact `$200/m` company pricing is now extracted and cited
  instead of disagreeing with the resolved evidence gap.
- `5a9a96b` → `d320cad`: RED/GREEN — compact memo prose prefers complete sentences and preserves a
  citation when content must be shortened.
- `a055ec5` → `fdcbc11`: RED/GREEN — the registry now truthfully enables the company-website source
  already used for labeled first-party evidence.
- Final automated checkpoint: 154 tests passed before the full coverage and packaging gates.

## 2026-08-24 — 20-candidate reliability hardening

- Repeated the live workflow with 20 current candidates and used the artifacts, not model claims, to
  measure coverage, citation integrity, decision stability, and evidence depth.
- `dc1a810` → `aa52ec8`: RED/GREEN — model sampling is deterministic where supported, baseline
  evidence preserves its real source identity, commercial gaps require independent evidence, and
  confidence is computed from evidence coverage instead of model self-rating.
- `277537f` → `cf8b85a`: RED/GREEN — Exa quota degradation is sanitized, stops repeated calls, keeps
  the memo pipeline alive, and appears as a reviewer-visible research-availability gap.
- `bcc3b22`, `05cddea` → `131c489`: RED/GREEN — baseline citation URLs must be public, verified
  regulatory evidence resolves commercial gaps, and evidence collected before a later quota failure
  is preserved.
- `5b9b6fb` → `ce88651`: RED/GREEN — confidence is capped at 65% without an independent source,
  even when many pages from the same company are available.
- Final live result: 20/20 candidates screened, four finalists analyzed, four one-page PDFs, and zero
  company failures. All four memos passed citation-ID and visual-layout checks. Exa was rate-limited,
  so all four memos explicitly disclose partial research; no independent-search result was invented.
- Final automated checkpoint: 158 tests passed with 91.87% total coverage; dependency and diff checks
  passed. Independent code and security reviews reported no remaining high or medium findings.
