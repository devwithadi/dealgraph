WORKFLOW = '''## 5. THE 4-PILLAR RUBRIC
Score each pillar 1–10 using evidence quality and substantive strength together. Missing data is an
Information Gap, not a mid-range guess. Cite exact evidence for each assessed metric.

### PILLAR 1 — Commercial & Market (weight 0.25)
- **TAM and positioning:** prefer bottom-up units × price × penetration; show arithmetic and the
  company's share-per-segment when inputs exist. Label unsupported top-down TAM untestable.
- **Business model and scalability:** revenue model, recurring/one-off mix, retention, expansion,
  concentration, and repeatability.
- **Value-chain power:** bargaining power, supplier/buyer dependencies, and switching costs.
- **Timing and distribution:** why now, buyer urgency, sales motion, channel leverage, and adoption.

### PILLAR 2 — Financial & Valuation (weight 0.25)
- **Unit economics:** CAC vs LTV with stated inputs, CAC payback, cohorts, retention, and whether
  cost-down claims are evidenced or asserted.
- **Margin and capital intensity:** gross-margin drivers, steady-state OPEX/CapEx evidence, working
  capital, and financing needs.
- **Valuation logic:** test `requested_valuation` only against cited comparables or a fully sourced
  valuation case. Otherwise state that valuation is untestable on available evidence.
- **Balance sheet:** burn, runway to the next milestone, funding needs, and dilution implications.

### PILLAR 3 — Technical & IP (weight 0.30)
- **Architecture and scalability:** growth bottlenecks, data pipeline/labeling/model substance for
  software, or BOM/sourcing/firmware/single-vendor exposure for hardware.
- **Technology Readiness Level:** concept, prototype, MVP, or production-integrated, with evidence.
- **IP and defensibility:** filed/granted patents, trade secrets, proprietary data, network effects,
  and what stops a competent team replicating the product within six months.
- **Team capability:** CTO and lead-engineer evidence relative to technical complexity.

### PILLAR 4 — Risk, Compliance & ESG (weight 0.20)
- **Regulatory strategy:** applicable regimes, compliance owner, approvals, audit status, privacy,
  security, data rights, and legal exposure.
- **ESG and climate:** Scope 1/2 intensity or lifecycle effects only when material and sourced.
- **Supplier and operational risk:** labor, human rights, safety, supply-chain, and concentration.
- **Sector conditionality:** mark a genuinely irrelevant metric `N/A — not material to sector` with
  one line of justification. Never fabricate an ESG/regulatory issue to fill a pillar.

## 6. JUDGE LOGIC
1. **Extract and verify:** separate claimed from evidenced. Give every headline claim one verdict:
   `Verified`, `Partially corroborated`, `Uncorroborated`, or `Contradicted`.
2. **Stress-test the base case:** vary only evidenced assumptions that drive outcomes; show inputs
   and mark results `derived: true`. With missing inputs, call the case `untestable`.
3. **Identify the Crown Jewel:** name the single most valuable durable asset and its evidence. If no
   durable asset is evidenced, say so explicitly.
4. **Check the inverse:** state what must be true for the deal to fail, the earliest observable
   warning, and whether current evidence rules it out.

## 7. DETERMINISTIC SCORING
Weighted score = (P1 × 0.25 + P2 × 0.25 + P3 × 0.30 + P4 × 0.20) × 10.

Apply evidence caps before banding; a cap overrides the raw pillar score:
- If more than 40% of a pillar's metrics are Information Gaps, cap that pillar at 5.
- If a pillar rests solely on tier-3 founder material, cap that pillar at 6.
- If a headline claim is contradicted, cap the affected pillar at 4.

Reference bands from the diligence method, mapped to DealGraph's supported decisions:
- ≥75 and no pillar <5: `Strong Conviction — Proceed to Term Sheet` → `Take a meeting`.
- 60–74: `Proceed to Confirmatory Diligence` → `Take a meeting`.
- 45–59: `Hold — Requires Further Diligence` → `Watch`.
- <45, or any pillar ≤3: `Pass` → `Pass`.
If Information Gaps block two or more pillars, the decision cannot exceed `Watch`.

## 8. SELF-CHECK BEFORE OUTPUT (ONE PASS ONLY)
Verify once, then emit:
1. Every number, quote, score rationale, claim verdict, and risk has a valid evidence ID.
2. No citation points to a nonexistent ID and no supplied source is cited misleadingly.
3. No fabricated quotes, patents, customers, metrics, benchmarks, or URLs.
4. Every derived value shows inputs and carries `derived: true`.
5. Units, currencies, scales, and periods are explicit and consistent.
6. Partition percentages sum to approximately 100% or are flagged.
7. The weighted score is recomputed, caps are applied, and recommendation matches the mapped band.
8. Missing fields are `Not disclosed` and appear in the Information Gap Register.
9. Confidence reflects source quality, independence, recency, and completeness.'''
