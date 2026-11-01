WORKFLOW = '''# SCREENING WORKFLOW

## 1. Inputs
The following JSON is the complete screening batch:
```json
<input_json>
```

## 2. Evaluate every candidate independently
For each candidate:
1. Identify the actual product, primary user/buyer, painful workflow, and claimed outcome.
2. Compare that meaning—not isolated words—to the requested topic and investment thesis.
3. Test whether the company could plausibly deliver measurable ROI, repeatable distribution,
   durable differentiation, and venture-scale expansion. At screening, these are hypotheses, not
   verified facts.
4. Separate explicit input facts from reasonable interpretation. Treat missing team size, industry,
   tags, or description as missing evidence rather than a negative fact.
5. State the strongest reason to advance and the strongest reason not to advance.
6. Assign `fit_score` from 0–100 using these anchors:
   - 85–100: direct, unusually strong semantic fit;
   - 65–84: credible fit deserving research;
   - 45–64: adjacent or ambiguous, but plausible enough to investigate;
   - 20–44: weak connection with no credible thesis path;
   - 0–19: clearly irrelevant or contradictory.
7. Set `advance=true` for credible direct, adjacent, or ambiguous fits where research could resolve
   uncertainty. Set it false only when the supplied facts make the company clearly irrelevant.

## 3. Batch consistency
Apply the same standard to the entire batch. Do not rank candidates against each other, enforce a
quota, or reject a company merely because another looks stronger.'''
