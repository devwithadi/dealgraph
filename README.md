# DealGraph

DealGraph is a two-stage, evidence-first CLI for screening recently launched YC companies and writing cited seed-investment memos.

It deliberately separates inexpensive breadth from expensive depth:

```text
YC public JSON
  → launch-date eligibility
  → batched small-model semantic screening
  → Agent Reach / Exa research for finalists
  → main-model synthesis, score, recommendation, and memo
```

There is no topic keyword filter and no deterministic investment score. The topic is supplied to both LLM stages, and the synthesizer owns the final `Take a meeting`, `Watch`, or `Pass` judgment.

## Quick start

```bash
uv sync --extra dev
agent-reach doctor --json
uv run dealgraph run --topic "AI agents for SMBs" --output data/runs/latest
```

By default, DealGraph screens active YC companies launched in the last 30 days. Use `--batch W26` to restrict to a specific YC batch, or `--limit 50` as an emergency cap after date selection.

### Offline Replay Mode

Re-generate both `.md` and `.pdf` investment memos from stored run artifacts without making network or LLM calls:

```bash
uv run dealgraph replay --run-dir data/runs/latest
```

---

## AI Workflow & Technical Architecture

For a deep-dive on the engineering journey, prompt evolution (v1-v5 screening, v1-v4 synthesis), empirical multi-model benchmarks, failure modes & defensive guardrails, and AI agent co-engineering log, see:

📖 **[docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md)**

---

## Model Selection & Providers

DealGraph supports seamless multi-provider execution with built-in model aliasing:

| Provider | CLI `--provider` | Default Screening | Default Synthesis | Model Aliases |
|---|---|---|---|---|
| **AWS Bedrock** (default) | `bedrock` | `amazon.nova-micro-v1:0` | `amazon.nova-lite-v1:0` | `nova-micro`, `nova-lite`, `nova-pro`, `llama-3.3-70b`, `claude-3.5-sonnet` |
| **OpenAI** | `openai` | `gpt-4.1-nano` | `gpt-4.1-mini` | Standard OpenAI models |
| **OpenRouter** | `openrouter` | `qwen/qwen-2.5-72b-instruct` | `qwen/qwen-2.5-72b-instruct` | `qwen-2.5-72b`, `qwen-2.5-32b` |
| **DeepSeek** | `deepseek` | `deepseek-chat` | `deepseek-chat` | `deepseek-v3`, `deepseek-r1` |
| **DashScope (Alibaba)** | `dashscope` | `qwen-turbo` | `qwen-plus` | `qwen-max`, `qwen-plus`, `qwen-turbo` |
| **Zhipu AI (GLM)** | `zhipu` | `glm-4-air` | `glm-4-plus` | `glm-4`, `glm-4-plus`, `glm-4-air`, `glm-5` |

Specify custom models via `--model`, `--screening-model`, or `--synthesis-model`:

```bash
uv run dealgraph run --topic "AI infrastructure" --provider bedrock --model llama-3.3-70b
```

## Configuration

The launch window is controlled by the environment:

```bash
DEALGRAPH_LOOKBACK_DAYS=60 uv run dealgraph run --topic "AI infrastructure"
```

`DEALGRAPH_LOOKBACK_DAYS` defaults to `30` and must be an integer from 1 to 3650. YC exposes `launched_at`; DealGraph uses that as the available posting/launch date and excludes records without one.

Amazon Bedrock is the default provider:

```bash
AWS_BEARER_TOKEN_BEDROCK=... \
AWS_REGION=us-east-1 \
BEDROCK_SCREENING_MODEL_ID=amazon.nova-micro-v1:0 \
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0 \
uv run dealgraph run --topic "AI agents"
```

`AWS_BEARER_TOKEN_BEDROCK` is AWS's official environment variable for a Bedrock
API key. Boto3 consumes it directly; DealGraph never forwards or persists the
token. If it is absent, Boto3's normal credential chain still supports AWS
profiles, temporary credentials, and workload IAM roles.

Both Bedrock model IDs are passed to Bedrock unchanged. They may name any
text-generation base model or inference profile that supports the Bedrock
Converse API and system prompts in the configured region; embeddings,
image-only models, and imported models are outside this client contract. Nova
Micro and Nova Lite are only defaults. This allows a small inexpensive model
for screening and a different main model for final synthesis. If an ARN is
configured, its AWS account ID is redacted in `manifest.json`.

To load a local file based on [`.env.example`](.env.example), use:

```bash
uv run --env-file .env dealgraph run --topic "AI agents"
```

OpenAI and public HTTPS OpenAI-compatible gateways are also supported:

```bash
OPENAI_API_KEY=... \
OPENAI_SCREENING_MODEL=gpt-4.1-nano \
OPENAI_MODEL=gpt-4.1-mini \
uv run dealgraph run --topic "AI agents" --provider openai
```

Custom `OPENAI_BASE_URL` values must use public HTTPS on port 443. Credentials, prompts, model responses, and authorization headers are never written to logs or artifacts.

## Screening and call volume

Eligible companies are sent to the small screening model in batches of 20. Each company receives an LLM decision containing `advance`, `fit_score`, and a concise rationale. Invalid or incomplete model responses are recorded as failures; there is no keyword or deterministic fallback.

For `N` eligible companies and `F` finalists, a successful run makes:

- `ceil(N / 20)` small-model screening calls
- `F` Agent Reach research calls
- `F` main-model synthesis calls

Only companies advanced by the screening model incur research and synthesis cost.

The two LLM stages have separate prompt packages under `app/prompts/screening/`
and `app/prompts/synthesis/`. Each stage keeps its persona, workflow,
guardrails, and JSON output contract in separate modules, then assembles them
into one prompt at its public package entrypoint. Screening remains focused on
high-recall semantic triage; synthesis contains the full evidence-governed VC
judge method used for the final memo.

## Research

All finalist web research is routed through Agent Reach's Exa backend using `mcporter`. DealGraph no longer crawls company pages or queries Hacker News directly.

The adapter uses a fixed subprocess argument list, does not invoke a shell, limits execution time and output size, removes secrets from the child environment, and rejects results from PitchBook, Crunchbase, and LinkedIn. Those vendors are not scraped. PitchBook requires a separately licensed API and permitted use.

Run this before a live job:

```bash
agent-reach doctor --json
mcporter list exa --schema --json
```

## Outputs

Every run creates:

```text
data/runs/latest/
├── input.json
├── candidates.json
├── screenings.json
├── shortlist.json        # synthesis decisions other than Pass
├── manifest.json
├── evidence/<finalist>.json
├── analyses/<finalist>.json
└── memos/
    ├── <finalist>.md     # Cited Markdown investment memo
    └── <finalist>.pdf    # Double-column vector PDF memo (ReportLab)
```

The manifest records the launch cutoff, eligible/screened/finalist/selected/memo counts, both model IDs, provider, Agent Reach source, failures, and one validated request ID. YC and OpenAI HTTP requests receive `X-Kong-Request-ID`; Bedrock calls receive the same ID in `requestMetadata`. The Agent Reach subprocess receives it as `DEALGRAPH_REQUEST_ID` for local correlation.

Normal output is concise:

```text
Screened 48/48 companies; created 6/6 finalist memos; selected 4.
Memos: /absolute/path/data/runs/latest/memos
Request ID: req-5ae470bb25d84a87
```

Use `--json` for automation and `--verbose` for operational logs.

## Offline Behavior & Replay

Fresh candidate screening requires LLM semantic triage. When re-generating investment memos from previously recorded runs, use `dealgraph replay` to produce both Markdown and vector PDF memos without network or LLM calls:

```bash
uv run dealgraph replay --run-dir data/runs/latest
```

## Verify

```bash
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
uv pip check
git diff --check
```

Python 3.10+ and `uv` are expected. Total test coverage must remain at or above 80%.
