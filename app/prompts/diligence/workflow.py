WORKFLOW = """# DILIGENCE WORKFLOW

The following JSON is the complete evaluation input:
```json
<input_json>
```

Return exactly one gap for every diligence pillar: <pillar_values>. Judge whether the supplied
evidence resolves each pillar,
state the remaining uncertainty and severity, and cite the resolving evidence ID when resolved.

Generate at most one focused follow-up search query for each unresolved gap and none for resolved
gaps. Preserve the requested hop on every query and use the exact pillar value associated with that
gap."""
