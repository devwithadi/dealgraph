WORKFLOW = '''## 5. THE 4-PILLAR RUBRIC & DEEP INSTITUTIONAL AUDIT
Score each pillar 1–10 using evidence quality and substantive strength together. Missing data is an
Information Gap, not a mid-range guess. Construct detailed, exhaustive, institutional-grade multi-paragraph
analyses for every section. Cite exact evidence IDs (e.g. `[ev-001]`) for every assessed metric and fact.

### PILLAR 1 — Commercial & Market (weight 0.25)
- **Bottom-Up TAM / SAM Breakdown:** Formulate a rigorous bottom-up TAM/SAM model: target unit volume ×
  Annual Contract Value (ACV) × addressable market penetration rate. Detail the arithmetic explicitly.
  Label unsupported top-down market claims as untestable.
- **Ideal Customer Profile (ICP) & Unit Economics:** Characterize the exact target buyer persona (e.g.,
  enterprise SecOps, mid-market data engineering, FinTech compliance), pain severity, budget ownership,
  and ACV expectations.
- **Competitor Comparison Matrix:** Compare positioning against both established legacy incumbents and
  venture-backed AI startups across features, pricing, and architecture.
- **Value-Chain Power & Switching Costs:** Assess supplier and platform dependencies, workflow integration
  depth, and data gravity that create durable switching costs.
- **Macro & Technological Catalysts ("Why Now"):** Detail specific technological inflections (e.g.,
  sub-second latency LLMs, agentic orchestration, new compliance mandates) driving urgent buyer demand.

### PILLAR 2 — Financial & Valuation (weight 0.25)
- **Comprehensive Pricing Breakdown:** Audit all known monetization tiers with exact tier names (e.g.,
  Starter, Pro, Team, Enterprise), explicit price points ($/month, $/seat, usage metering), feature
  packaging, and billing cadence (annual vs monthly).
- **Unit Economics & Margins:** Analyze Gross Margin profile (separating core SaaS 75–85% from AI inference
  or human-in-the-loop 45–60%), estimated CAC payback period, expansion mechanics, and customer churn.
- **Valuation Logic & Capitalization:** Evaluate total capital raised, lead investors, historical rounds
  (Pre-Seed, Seed, Series A), estimated valuation comps, burn rate, and runway to next milestone.
- **Sales Motion & Cycle:** Evaluate distribution velocity (product-led growth vs enterprise sales cycles
  spanning 3–9 months).

### PILLAR 3 — Technical & IP (weight 0.30)
- **Technical Architecture Deep-Dive:** Detail the core architecture: model routing and inference layer,
  agent framework, planning/reasoning loops, vector database memory, retrieval pipelines, and latency/throughput.
- **Integrations & Ecosystem:** Map all supported enterprise integrations (e.g., Snowflake, Slack, AWS,
  Salesforce, Postgres, GitHub) and API/SDK capabilities.
- **Technology Readiness Level (TRL 1–9):** Assess readiness from concept/prototype (TRL 3-4) to production-
  integrated enterprise deployment (TRL 7-9) with cited telemetry and benchmarks.
- **Defensibility Moats & IP:** Evaluate proprietary data flywheels, fine-tuned weights, patent filings,
  trade secrets, and estimate the replication timeframe for a well-funded engineering team.
- **Team Capability & Biographical Audit:** Conduct an exhaustive review of each founder and key executive:
  previous employers (Big Tech, scaleups), specific engineering/research roles, previous exits or startups
  founded, academic degrees, patents, GitHub footprint, open-source impact, and domain credibility.

### PILLAR 4 — Risk, Compliance & ESG (weight 0.20)
- **Critical Failure Scenarios (4–6 distinct scenarios):** Formulate 4 to 6 concrete, rigorous failure
  scenarios with specific operational tripwires and mitigation requirements.
- **Security & Compliance Posture:** Audit SOC2 Type II, ISO 27001, GDPR, HIPAA, data isolation, and
  regulatory bottlenecks.
- **Platform Dependencies:** Assess vulnerability to underlying model vendor changes (OpenAI, Anthropic),
  API rate limits, and cloud infrastructure concentration.
- **Sector Conditionality:** Mark genuinely irrelevant metrics `N/A — not material to sector` with a one-line
  justification. Never fabricate an ESG/regulatory issue to fill a pillar.

## 6. JUDGE LOGIC & STRATEGIC ASSESSMENTS
1. **Extract and Verify (Claim Verification Ledger):** Categorize every claim as `Verified`,
   `Partially corroborated`, `Uncorroborated`, or `Contradicted` with cited evidence.
2. **Crown Jewel Strategic Assessment:** Identify and thoroughly evaluate the single most valuable, durable,
   and proprietary asset that gives the company an enduring unfair advantage.
3. **The Inverse Case (Pre-Mortem Failure Conditions):** Articulate the exact failure mode and lethality
   conditions that would kill the business, early observable tripwires, and whether current evidence rules them out.
4. **Stress-Test the Base Case:** Vary evidenced drivers; show arithmetic and mark results `derived: true`.

## 7. DETERMINISTIC SCORING
Weighted score = (P1 × 0.25 + P2 × 0.25 + P3 × 0.30 + P4 × 0.20) × 10.

Apply evidence caps before banding; a cap overrides the raw pillar score:
- If more than 40% of a pillar's metrics are Information Gaps, cap that pillar at 5.
- If a pillar rests solely on tier-3 founder material, cap that pillar at 6.
- If a headline claim is contradicted, cap the affected pillar at 4.

Reference bands mapped to DealGraph decisions:
- ≥75 and no pillar <5: `Strong Conviction — Proceed to Term Sheet` → `Take a meeting`.
- 60–74: `Proceed to Confirmatory Diligence` → `Take a meeting`.
- 45–59: `Hold — Requires Further Diligence` → `Watch`.
- <45, or any pillar ≤3: `Pass` → `Pass`.
If Information Gaps block two or more pillars, the decision cannot exceed `Watch`.

## 8. SELF-CHECK BEFORE OUTPUT (ONE PASS ONLY)
Verify once, then emit:
1. Narrative fields (`summary`, `team`, `product`, `market`, `why_now`) contain exhaustive, multi-paragraph
   institutional-grade analyses rather than brief 1-line summaries.
2. Every number, quote, score rationale, claim verdict, and risk item carries inline evidence IDs `[ev-001]`.
3. No citation references a nonexistent ID and no supplied source is cited misleadingly.
4. Every derived value shows inputs and carries `derived: true`.
5. Missing fields are `Not disclosed` and registered in the Information Gap Register.
6. The weighted score is recomputed, caps applied, and recommendation aligns with the score band.'''
