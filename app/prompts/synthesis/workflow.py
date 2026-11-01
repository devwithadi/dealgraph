WORKFLOW = '''## 5. TAKE-HOME TRIAGE WORKFLOW
Produce a concise, evidence-led seed-investment assessment. This is a first-pass triage memo, not
exhaustive institutional diligence.

1. State a company-specific investment thesis: what the company does, why it may win, and the key
   evidence-backed reason to care.
2. Summarize the team, product, market, and timing using only supplied evidence. Write `Not disclosed`
   when evidence is missing.
3. Name the most important concrete risks and the founder questions that would resolve them.
4. Identify two or three findings that could materially change the decision.

## 6. FIVE-DIMENSION SCORECARD
Score each dimension from 0–10. Use the exact name and weight shown, cite at least one supplied evidence
ID in every rationale, and do not award unearned points for missing information.

- `workflow_pain` (25): frequency, severity, and cost of the customer problem.
- `speed_to_value` (20): how quickly and credibly a customer reaches measurable value.
- `compounding_advantage` (20): defensibility through integrations, proprietary data, or distribution.
- `team_execution` (15): evidence that the team can build, sell, and learn quickly.
- `market_distribution` (20): credible market size, ICP clarity, and route to customers.

The runtime recomputes the weighted total as `sum(score × weight) ÷ 10` and maps it to:
- ≥70: `Take a meeting`
- ≥45 and <70: `Watch`
- <45: `Pass`

## 7. EVIDENCE STANDARD
Keep fact and inference distinct. Cite each factual narrative and score rationale with supplied IDs such
as `[ev-001]`. Do not invent customer metrics, credentials, market sizes, financials, or competitors.

## 8. SELF-CHECK BEFORE OUTPUT
Verify the thesis is company-specific, all five dimensions appear exactly once with their fixed weights,
scores are 0–10, evidence IDs exist, and missing facts remain `Not disclosed`. Then emit the JSON once.'''
