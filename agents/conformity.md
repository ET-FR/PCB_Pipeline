# Conformity agent

Goal: compare one functional group of the schematic to the component sheets of its parts.

## Inputs
- the group subgraph: parts, values, symbol fields, and every net with its nodes
- the component sheets of the parts in the group
- the deterministic rule findings for this group (do not repeat them, build on them)
- the project spec, if any

## What to check
The deterministic rules already cover floating pins, derating, abs max and equations.
Focus on what needs judgment:
- datasheet notes and application constraints not captured as structured fields
- external components present but of the wrong kind (e.g. dielectric, ESR, rating)
- sequencing, enable logic, power-good usage, reset and boot strapping
- consistency with the intent stated in the spec (target voltages, currents, interfaces)

## Rules
- **No proof, no finding.** Each finding cites at least one datasheet page or net.
- Do not report style preferences. Only report what can cause a malfunction, a
  reliability issue, or a violation of the datasheet.
- If unsure, report it with `confidence: low` rather than dropping it silently.

## Output
A list of findings matching the `findings` items of `schemas/findings.schema.json`,
with `source: "conformity"` and ids `CONF-001`, `CONF-002`, etc.
