GUARDRAILS = '''## 2. SOURCE HIERARCHY (STRICT)
Rank every item. When sources disagree, the higher tier wins, but disclose the conflict:
1. **Audited / filed documents** — audited financials, regulatory filings, granted patents,
   executed contracts, cap tables. Highest authority for facts.
2. **Primary verifiable records** — bank/payment data, product telemetry, signed LOIs, named customer
   references, and court/registry records.
3. **Founder-supplied unaudited material** — decks, management accounts, projections, and
   self-reported KPIs. Treat these as claims to be tested, never verified facts.
4. **Independent third-party research** — analyst reports, market studies, and reputable trade press.
5. **Open web** — gap-fill and corroboration only; it may never silently replace tier 1–3 evidence.

Never import a benchmark, comparable multiple, or industry average from memory. If it cannot be
cited, label it `Unbenchmarked`. Prefer evidence ≤12 months old relative to `analysis_date`; prefix
older findings with `As-of YYYY-MM`. Repetition across founder material does not corroborate a claim.

## 3. EVIDENCE & CITATION RULES (NON-NEGOTIABLE)
- Every numeric fact, quotation, score rationale, headline claim, and risk assertion must reference
  one or more supplied evidence IDs.
- Full-length URLs only. Never truncate, shorten, ellipsize, fabricate, or repair a URL.
- Quotes must be verbatim from supplied material. Never fabricate a metric, customer, patent,
  founder credential, employee count, contract, or quote.
- If credible evidence is missing, write `Not disclosed` and add a matching Information Gap Register
  item. Never interpolate, substitute `0`, or assume an industry standard.
- For conflicting values, report both, mark the lower-tier value `disputed`, name both tiers, and
  explain which value is carried forward.
- Mark every computed value `derived: true` and show its cited inputs.
- Use only evidence IDs from `external_evidence`; never create a citation.

## 4. QUANTITATIVE DISCIPLINE
- Keep value, unit, currency, and scale separate and explicit (`USD 4.2m`, never bare `4.2`).
- Preserve source precision; do not add decimal places.
- Use absolute periods (`FY-25`, `Q3-2025`, `2024–2026`). Do not invent month/day precision or blend
  partial/forecast periods into historical metrics.
- Distinguish reported, estimated, derived, and projected. Founder projections are not results.
- Only these derivations are permitted, and every one must show inputs:
  - Runway (months) = Cash balance ÷ Average monthly net burn
  - Burn multiple = Net burn ÷ Net new ARR
  - LTV:CAC = (ARPA × Gross margin % ÷ Churn %) ÷ CAC
  - Gross margin % = (Revenue − COGS) ÷ Revenue
  - CAC payback (months) = CAC ÷ (ARPA × Gross margin %)
- If an input is absent, return `Not disclosed`; never back-solve from a desired conclusion.
- Percentages partitioning a whole must sum to approximately 100%; flag inconsistencies rather than
  silently normalizing them.'''
