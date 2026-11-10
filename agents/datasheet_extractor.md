# Datasheet extractor

Follow `agents/memory.md`: read the valid notes before working, write notes while working.

Goal: fill one component sheet that validates against `schemas/component_sheet.schema.json`.

## Rules
- Every value carries the page it was read from. No page, no value.
- Never infer or guess a value. If the datasheet does not give it, leave it out and
  add a line to `extraction.gaps`.
- Pin names must match the datasheet exactly, so the conformity agent can map them
  to the symbol pins.
- For each pin, set `requirement` from the datasheet text (for example an EN pin that
  "must not be left floating" is `no_float`).
- Equations must be Python-evaluable. Constants (VREF, etc.) go in `constants`,
  and each variable maps to the pins the corresponding part sits between.
- Set `criticality`: `power` for regulators and power switches, `mains` for anything
  connected to mains voltage.

## Output
The component sheet, saved as `library/component_sheets/<MPN>@<revision>.json`,
then validated with `pcb-pipeline validate-sheet`.
