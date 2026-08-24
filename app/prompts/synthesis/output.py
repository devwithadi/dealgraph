OUTPUT = '''## 9. SYNTHESIS OUTPUT CONTRACT
Return exactly one concise JSON object, with no Markdown or commentary. End factual text in `thesis`,
`summary`, `team`, `product`, `market`, `why_now`, `risks`, and dimension rationales with supplied inline
evidence IDs such as `[ev-001]`. `Unknown`, `Not disclosed`, and `N/A` are exempt.

{
  "thesis": "Company-specific investment thesis and defensible advantage [ev-001]",
  "summary": "Brief evidence-led investment conclusion [ev-001]",
  "team": "Relevant execution evidence or Not disclosed [ev-001]",
  "product": "Product, customer workflow, and differentiation [ev-001]",
  "market": "ICP, market evidence, and distribution motion [ev-001]",
  "why_now": "Evidence-backed timing catalyst [ev-001]",
  "risks": ["Concrete risk and its observable tripwire [ev-001]"],
  "open_questions": ["Specific founder diligence question"],
  "changes_mind": ["Decision-changing proof point", "Second proof point"],
  "dimensions": [
    {"name": "workflow_pain", "score": 0, "weight": 25, "rationale": "Reason [ev-001]", "evidence_ids": ["ev-001"]},
    {"name": "speed_to_value", "score": 0, "weight": 20, "rationale": "Reason [ev-001]", "evidence_ids": ["ev-001"]},
    {"name": "compounding_advantage", "score": 0, "weight": 20, "rationale": "Reason [ev-001]", "evidence_ids": ["ev-001"]},
    {"name": "team_execution", "score": 0, "weight": 15, "rationale": "Reason [ev-001]", "evidence_ids": ["ev-001"]},
    {"name": "market_distribution", "score": 0, "weight": 20, "rationale": "Reason [ev-001]", "evidence_ids": ["ev-001"]}
  ],
  "score": 0,
  "confidence": 0.0,
  "recommendation": "Take a meeting | Watch | Pass",
  "citations": ["ev-001"]
}

The runtime, not the model, treats the dimension-derived score and recommendation as authoritative.'''
