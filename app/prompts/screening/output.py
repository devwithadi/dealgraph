OUTPUT = '''# SCREENING OUTPUT CONTRACT

Return exactly one JSON object and no Markdown, commentary, or extra keys:
{
  "decisions": [
    {
      "slug": "exact input slug",
      "advance": true,
      "fit_score": 0,
      "rationale": "One concise sentence stating semantic fit and the decisive uncertainty"
    }
  ]
}

`fit_score` must be between 0 and 100. Preserve input order and include every candidate exactly once.'''
