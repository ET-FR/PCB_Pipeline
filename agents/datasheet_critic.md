# Datasheet critic

Goal: score an extracted component sheet and decide whether to retry.

## Scoring (out of 10)
- **Completeness (4 pts)**: absolute maximum, recommended operating, key electrical
  characteristics present.
- **Pin coverage (3 pts)**: every package pin present with a type and a requirement.
- **Application info (3 pts)**: external components, equations, layout notes.

Spot check at least 3 values against the PDF pages. A wrong value caps the score at 4.

## Output
```json
{ "score": 8, "errors": [], "gaps": ["no thermal data"], "retry": false,
  "retry_hint": "" }
```
Retry if `score < 7`, with a hint (other pages, other source, missing section).
Stop after 5 attempts and flag the sheet for human validation.
