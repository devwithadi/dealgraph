# DealGraph technical guide

DealGraph is a replayable command-line application that turns public startup information into evidence-backed seed-investment memos. It is intentionally sequential: a run handles 1–20 companies in a predictable order, preserves partial results, and writes every useful intermediate artifact to disk.

## Diagram set

| View | Explains | Use it when you need to |
| --- | --- | --- |
| [System architecture](system-architecture.html) | All application modules, external integrations, trust boundaries, and ownership of artifacts | Understand where a behavior belongs in the codebase |
| [Run lifecycle](run-lifecycle.html) | Online vs. offline execution, enrichment failure isolation, narrative-provider fallback, and exit behavior | Trace one command from input validation to summary |
| [Run artifacts](run-artifacts.html) | The exact output tree and the contract of every generated file | Inspect, replay, debug, or consume a finished run |
| [Pipeline data flow](pipeline-data-flow.html) | The transformations from source records to evidence, analysis, and memos | Follow the payloads rather than the Python modules |

## Application map

| Module | Responsibility | Primary entry points |
| --- | --- | --- |
| `app/cli/` | Parse `dealgraph run`, configure logging, bind the request ID, print the final summary, and provide the top-level error boundary | `app/cli/main.py` |
| `app/core/` | Application errors, request-ID context, safe log formatting, common HTTP headers, and public-URL validation | `errors.py`, `logging.py`, `urls.py` |
| `app/domain/` | Immutable Pydantic contracts and closed enums used across the pipeline | `models.py`, `enums.py` |
| `app/sourcing/` | YC candidate selection, source registry, SSRF-safe website fetching, and YC/website/Hacker News evidence adapters | `candidates.py`, `policy.py`, `evidence.py`, `registry.py` |
| `app/analysis/` | Deterministic rubric scoring, financial extraction, citation validation, and optional Bedrock/OpenAI narrative generation | `scoring.py`, `service.py`, `providers.py` |
| `app/prompts/` | Persona, workflow, output contract, and prompt assembly for model providers | `builder.py`, `persona.py`, `workflow.py`, `output.py` |
| `app/reporting/` | Render an analysis and its evidence into a cited Markdown investment memo | `memo.py` |
| `app/pipeline/` | Orchestrate one complete run, isolate failures per company, and write run artifacts | `service.py` |

Dependencies point inward: **CLI → pipeline → sourcing / analysis / reporting → domain / core**. Lower layers do not import the pipeline or CLI.

## What happens during a run

1. The CLI validates arguments, configures logs, and creates or validates a request ID.
2. `Pipeline.run()` validates the topic and mode, creates the artifact directories, and chooses either a local candidate file or the public YC feed.
3. Candidate selection normalizes records, filters by topic and optional batch, deduplicates by hostname, ranks matches, and caps the list at 20.
4. For every selected company, DealGraph creates YC evidence. In online mode it may also collect first-party website pages and the strongest matching Hacker News record.
5. Website fetching validates each URL and redirect, rejects blocked vendors and non-public targets, obeys `robots.txt`, accepts HTML only, and limits responses to 2 MB.
6. Analysis calculates six deterministic dimensions, confidence, and recommendation. Bedrock or an OpenAI-compatible endpoint may supply a cited narrative; unavailable or invalid provider output falls back to a deterministic narrative.
7. The pipeline writes evidence JSON, analysis JSON, and a cited Markdown memo for each successful company. One company’s failure becomes an `evidence_gaps` entry and does not abort the rest of the run.
8. A manifest records the run ID, request ID, selected sources, provider/mode/model, counts, and gaps. The CLI prints a concise summary and returns exit code `1` if any company failed.

## Modes and integrations

| Mode or integration | Behavior |
| --- | --- |
| `--offline --source-file <file>` | Makes zero network calls, skips website and Hacker News enrichment, and forces deterministic analysis. |
| Live YC feed | Uses `https://yc-oss.github.io/api/companies/all.json` when no source file is supplied. |
| Company websites | First-party HTML only, through the safe fetch policy. |
| Hacker News | Queries Algolia’s HN API and keeps the highest-signal matching story. |
| Amazon Bedrock | Default narrative provider through Boto3 `Converse`; request metadata carries the request ID. |
| OpenAI-compatible provider | Optional HTTPS-only endpoint on port 443; its API key is never persisted or logged. |
| Deterministic fallback | Always available when no provider is selected, unavailable, malformed, or disabled by offline mode. |

## Trust and data boundaries

- The source registry is the allow-list. PitchBook is disabled, and Crunchbase and LinkedIn are blocked from web fetching.
- Every outbound HTTP request includes `X-Kong-Request-ID`. The same ID is recorded in `manifest.json` and returned in the run summary.
- Facts that lack evidence remain `null` or `Unknown`. The narrative parser rejects citations that do not refer to collected evidence IDs.
- Run artifacts are the only persistent store. There is no database, queue, background worker, or API server.

## Useful code paths

- CLI and exit behavior: [`app/cli/main.py`](../app/cli/main.py)
- Orchestration and artifacts: [`app/pipeline/service.py`](../app/pipeline/service.py)
- Safe fetching policy: [`app/sourcing/policy.py`](../app/sourcing/policy.py)
- Source registry: [`app/sourcing/registry.py`](../app/sourcing/registry.py)
- Scoring and provider fallback: [`app/analysis/service.py`](../app/analysis/service.py), [`app/analysis/providers.py`](../app/analysis/providers.py)
- Immutable data contracts: [`app/domain/models.py`](../app/domain/models.py)
