OUTPUT = '''## 9. SYNTHESIS OUTPUT CONTRACT
The application renders a compact Markdown memo and Source Registry from this strict schema. Your
JSON fields must collectively preserve these diligence components:
1. Investment Thesis & Crown Jewel — evidenced thesis, Crown Jewel, inverse case, confidence.
2. Evidence-Based Scoring Matrix — all four pillar rationales, weights, caps, and weighted score.
3. Claim Verification Ledger — claim, verdict, evidence ID, conflict note.
4. Financial & Equity Drill-Down — runway, unit economics, margins, valuation testability, dilution.
5. Technical Architecture & Scalability Review — TRL, bottleneck, IP, replication risk, team fit.
6. Stress Test — assumption, base, stressed case, effect, inputs, or `untestable`.
7. Information Gap Register — missing item, pillar, why it matters, and how to close it.
8. Final Recommendation & Action Items — mapped decision, rationale, and founder questions.
9. Source Registry — supplied evidence IDs resolve to full URLs in the rendered memo.

Place the most important thesis/Crown Jewel/inverse findings in `summary`; technical/IP findings and
relevant claim verdicts in `product`; Commercial findings in `market`; Financial, compliance, ESG,
stress-test, and cap findings in `risks`; gap-register items in `open_questions`; and specific
evidence requests/action items in `changes_mind`.

End every factual string in `summary`, `team`, `product`, `market`, and `why_now`, and every item in
`risks`, with one or more inline evidence IDs such as `[ev-001]`. `Unknown`, `Not disclosed`, and
`N/A` are exempt. The runtime rejects uncited factual narrative.

Return exactly one JSON object, no Markdown, commentary, or extra keys:
{
  "summary": "Detailed IC conclusion with Crown Jewel, inverse case, score rationale, and confidence",
  "team": "Cited team capability assessment or Not disclosed",
  "product": "Cited technical/IP review, claim verdicts, TRL, scalability, and replication risk",
  "market": "Cited Commercial & Market assessment, business model, distribution, and power",
  "why_now": "Cited timing case or Not disclosed",
  "risks": ["Cited financial, technical, compliance, ESG, stress-test, or evidence-cap finding"],
  "open_questions": ["Information Gap: missing item | pillar | why it matters | how to close"],
  "changes_mind": ["Specific decision-changing evidence request", "Second concrete action item"],
  "score": 0,
  "confidence": 0.0,
  "recommendation": "Take a meeting | Watch | Pass",
  "citations": ["evidence-id"]
}

`score` is 0–100, `confidence` is 0–1, `changes_mind` contains two or three items, and `citations`
contains every evidence ID relied on anywhere in the response.'''
