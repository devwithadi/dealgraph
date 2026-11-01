OUTPUT = '''## 9. SYNTHESIS OUTPUT CONTRACT & INSTITUTIONAL MEMO SCHEMA
The application renders a publication-grade Markdown memo, executive scorecard, and Source Registry
from this strict schema. Your JSON fields must collectively preserve these diligence components and
contain exhaustive, multi-paragraph, institutional-grade analyses rather than brief 1-line summaries:

1. Investment Thesis & Crown Jewel — evidenced thesis, Crown Jewel, inverse case, confidence.
2. Evidence-Based Scoring Matrix — all four pillar rationales, weights, caps, and weighted score.
3. Claim Verification Ledger — claim, verdict, evidence ID, conflict note.
4. Financial & Equity Drill-Down — runway, unit economics, margins, valuation testability, dilution.
5. Technical Architecture & Scalability Review — TRL, bottleneck, IP, replication risk, team fit.
6. Stress Test — assumption, base, stressed case, effect, inputs, or `untestable`.
7. Information Gap Register — missing item, pillar, why it matters, and how to close it.
8. Final Recommendation & Action Items — mapped decision, rationale, and founder questions.
9. Source Registry — supplied evidence IDs resolve to full URLs in the rendered memo.

Field Content Expectations:
- `summary`: Multi-paragraph Investment Committee synthesis detailing core investment thesis, Crown Jewel
  proprietary asset evaluation, inverse pre-mortem failure modes, score rationale across all pillars, and
  confidence calibration.
- `team`: Deep biographical audit of each founder and key executive (prior employers, specific engineering/
  research roles, previous exits or startups founded, academic degrees, patents, GitHub footprint, and domain
  mastery) with cited evidence IDs `[ev-001]`.
- `product`: Multi-paragraph technical deep-dive (core architecture, model routing/reasoning layer, agent
  framework, database/vector memory, integrations ecosystem, UX workflow, TRL assessment, and defensibility
  moats) with cited evidence IDs `[ev-001]`.
- `market`: Multi-paragraph commercial assessment (bottoms-up TAM/SAM sizing breakdown, buyer persona/ICP
  unit economics, competitor comparison matrix of incumbents vs startups, and switching costs) with cited
  evidence IDs `[ev-001]`.
- `why_now`: Multi-paragraph analysis of technological inflections, macroeconomic catalysts, and market urgency
  driving immediate customer adoption with cited evidence IDs `[ev-001]`.
- `risks`: Array of 4–6 distinct, concrete failure scenarios with explicit operational tripwires, mitigation
  requirements, and cited evidence IDs `[ev-001]`.
- `open_questions`: Array of Information Gap Register items (`missing item | pillar | why it matters | how to close`).
- `changes_mind`: 2–3 high-leverage decision-changing evidence requests or founder diligence action items.
- `score`: Deterministic weighted score (0–100) based on the rubric and applied caps.
- `confidence`: Numerical score (0.0–1.0) calibrated to evidence source quality and completeness.
- `recommendation`: Exact decision string (`Take a meeting` | `Watch` | `Pass`).
- `citations`: Array containing every evidence ID referenced anywhere in the response.

End every factual statement in `summary`, `team`, `product`, `market`, and `why_now`, and every item in
`risks`, with one or more inline evidence IDs such as `[ev-001]`. `Unknown`, `Not disclosed`, and `N/A` are
exempt. The runtime rejects uncited factual narrative.

Return exactly one JSON object, no Markdown, commentary, or extra keys:
{
  "summary": "Detailed multi-paragraph IC executive conclusion with Crown Jewel asset, inverse pre-mortem failure mode, score rationale, and confidence rating",
  "team": "Deep biographical audit of each founder with prior engineering roles, previous exits, degrees, and domain mastery [ev-001]",
  "product": "Multi-paragraph technical architecture deep-dive, agent framework, database/vector memory, integrations ecosystem, TRL, and IP defensibility [ev-001]",
  "market": "Multi-paragraph commercial analysis, bottom-up TAM/SAM sizing, ICP unit economics, competitor comparison matrix, and switching costs [ev-001]",
  "why_now": "Multi-paragraph analysis of technological catalysts and macro inflections driving urgent adoption [ev-001]",
  "risks": [
    "Concrete failure scenario 1 with specific tripwires and mitigation requirements [ev-001]",
    "Concrete failure scenario 2 with platform dependency analysis [ev-002]",
    "Concrete failure scenario 3 with competitive or regulatory bottlenecks [ev-003]",
    "Concrete failure scenario 4 with customer acquisition or margin compression risks [ev-001]"
  ],
  "open_questions": [
    "Information Gap: missing item | pillar | why it matters | how to close"
  ],
  "changes_mind": [
    "Specific decision-changing evidence request or pilot validation milestone",
    "Second concrete technical benchmark or customer verification requirement"
  ],
  "score": 0,
  "confidence": 0.0,
  "recommendation": "Take a meeting | Watch | Pass",
  "citations": ["ev-001", "ev-002", "ev-003"]
}'''
