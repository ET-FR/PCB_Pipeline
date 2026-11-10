# Instructions for Claude Code

This repository is a design review pipeline for KiCad projects. When working here:

- The Python core (`src/pcb_pipeline`) must stay deterministic. Anything that needs
  judgment belongs in an agent prompt under `agents/`, not in Python.
- Component sheets and findings must validate against `schemas/`. Run
  `pcb-pipeline validate-sheet` on any sheet you create or edit.
- Rule of evidence: a finding without `evidence` (datasheet page, net, or calculation)
  is invalid and must be dropped, never "softened".
- Never invent datasheet values. If a value cannot be found in the PDF, leave the field
  out and lower the sheet's critic score.
- Run `pytest` before committing.

## Running a review

Use `/review <path-to-project>` (see `.claude/commands/review.md`).
