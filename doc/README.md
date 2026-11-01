# DealGraph technical guide

DealGraph is a live, evidence-first command-line application that turns public startup information
into cited one-page PDF investment memos plus auditable JSON artifacts. It is intentionally
sequential: a run handles one bounded batch, preserves the useful intermediate files, and keeps the
review surface small enough to inspect quickly.

## Diagram set

| View | Explains | Use it when you need to |
| --- | --- | --- |
| [System architecture](system-architecture.html) | All application modules, external integrations, trust boundaries, and ownership of artifacts | Understand where a behavior belongs in the codebase |
| [Run lifecycle](run-lifecycle.html) | Live execution, enrichment failure isolation, provider validation, and exit behavior | Trace one command from input validation to summary |
| [Run artifacts](run-artifacts.html) | The exact output tree and the contract of every generated file | Inspect, debug, or consume a finished run |
| [Pipeline data flow](pipeline-data-flow.html) | The transformations from source records to evidence, analysis, and memos | Follow the payloads rather than the Python modules |

## Application map

| Module | Responsibility | Primary entry points |
| --- | --- | --- |
| `app/cli/` | Parse `dealgraph run`, configure logging, bind the request ID, print the final summary, and provide the top-level error boundary | `app/cli/main.py` |
| `app/core/` | Application errors, request-ID context, safe log formatting, common HTTP headers, and public-URL validation | `errors.py`, `logging.py`, `urls.py` |
| `app/domain/` | Immutable Pydantic contracts and closed enums used across the pipeline | `models.py`, `enums.py` |
| `app/sourcing/` | Candidate selection, source registry, SSRF-safe website fetching, and public evidence adapters | `candidates.py`, `policy.py`, `evidence.py`, `registry.py` |
| `app/analysis/` | Five-dimension score validation, financial extraction, citation checks, and provider-backed narrative generation | `scoring.py`, `service.py`, `providers.py` |
| `app/prompts/` | Persona, workflow, output contract, and prompt assembly for screening and synthesis | `screening/`, `synthesis/` |
| `app/reporting/` | Render an analysis and its evidence into a cited one-page PDF memo | `memo.py`, `pdf.py` |
| `app/pipeline/` | Orchestrate one complete run, isolate failures per company, and write run artifacts | `service.py` |

Dependencies point inward: **CLI → pipeline → sourcing / analysis / reporting → domain / core**. Lower layers do not import the pipeline or CLI.

## What happens during a run

1. The CLI validates arguments, configures logs, and creates or validates a request ID.
2. `Pipeline.run()` validates the topic and provider credentials before sourcing, creates the
   artifact directories, and chooses either a local candidate file or the public YC feed.
3. Candidate selection normalizes records, filters by launch window and optional batch, preserves up
   to the requested limit, and sends the full eligible set to semantic screening.
4. Screening runs in bounded batches and returns one decision for every candidate slug. Only
   finalists move on to deeper research.
5. Finalist evidence combines YC, company pages, and focused public web research through the enabled
   source registry. URL fetching validates redirects, blocks non-public targets, obeys `robots.txt`,
   accepts HTML only, and limits responses to 2 MB.
6. Analysis validates five fixed score dimensions, recomputes the weighted total and recommendation
   in Python, and uses a model only for the cited narrative fields.
7. The pipeline writes evidence JSON, analysis JSON, shortlist/screening JSON, and a cited one-page
   PDF memo for each successful company. One company’s failure becomes a safe `gaps.json` entry and
   does not abort the rest of the run.
8. A manifest records the run ID, request ID, selected provider/models, counts, and artifact names.
   The CLI prints a concise summary and returns exit code `1` if any company failed.

## Modes and integrations

| Mode or integration | Behavior |
| --- | --- |
| `--source-file <file>` | Uses a local candidate file for sourcing, then continues with the same live screening and analysis pipeline. |
| Live YC feed | Uses `https://yc-oss.github.io/api/companies/all.json` when no source file is supplied. |
| Agent Reach / Exa | Supplies focused public-web evidence for finalists when enabled in the source registry. |
| Company websites | First-party HTML only, through the safe fetch policy. |
| Amazon Bedrock | Default provider through Boto3 `Converse`; request metadata carries the request ID. |
| Other model providers | Named API-key providers and validated OpenAI-compatible HTTPS endpoints are supported. |
| Sanitized artifacts | Every live run writes reviewable JSON plus one-page PDF memos without storing prompts, raw responses, or secrets. |

## Trust and data boundaries

- The source registry is the allow-list. PitchBook is disabled, and Crunchbase and LinkedIn are
  blocked from web fetching.
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
