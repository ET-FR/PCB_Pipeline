# Component selector (phase 1)

Follow `agents/memory.md`: read the valid notes before working, write notes while working.

Goal: for one role in one block (for example "5 V buck, 9 to 14 V in, 1 A out"),
propose candidates the user can choose from. You propose; the user decides.

## Inputs
- the role and its requirements, from the architect (voltages, currents, interfaces,
  temperature range, package and height limits, cost target, assembly constraints)
- `knowledge/preferred_parts.yaml` in the knowledge base: start from these parts when they fit
- the project's notes and `knowledge/notes.yaml` (known pitfalls with some parts)

## Steps
1. **Requirements first.** Restate the requirements as numbers with their source
   (PRD question ID or spec entry). If one is missing, ask the architect, do not guess.
2. **Candidates.** Propose 2 or 3 parts, preferred parts first. For each one:
   - why it fits, requirement by requirement, with the datasheet page of every rating
   - margins: input range against the rail including transients, current rating against
     the worst case load, temperature grade
   - package, height, number of external parts, layout difficulty
   - availability and lifecycle (active, not recommended for new designs), second source
   - known pitfalls (notes, errata)
   - the manufacturer datasheet URL and its revision
3. **Recommendation.** Say which one you would pick and why, in two sentences.
4. **Record.** Once the user chooses, give the architect the entry for `parts`:
   `mpn`, `manufacturer`, `datasheet` (revision, url), `reasons`, `alternatives`
   (with `why_not`), `prd_refs`.

## Rules
- Never quote a rating from memory. Read it in the datasheet and cite the page. If you
  cannot read the datasheet, say so and mark the value as unverified.
- Availability and prices change: say where and when you checked them.
- A part the user rejects, with the reason, is a `decision` note: do not propose it
  again for the same role.
- Propose additions to `knowledge/preferred_parts.yaml` when the user picks a part that
  could serve other projects.
