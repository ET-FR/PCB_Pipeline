# Roadmap

Ordered by value: the earlier phases catch the most expensive errors.

## Done

- [x] **Foundations**: repo structure, `pipeline.yaml`, `kicad-cli` import, pre-commit hook.
- [x] **Formats (first draft)**: JSON Schemas for component sheets and findings.
- [x] **Phase 0 question list** (`knowledge/phase0_questions.md`) and interviewer prompt.
- [x] **Agent memory format**: `schemas/notes.schema.json`, `agents/memory.md`,
  `pcb-pipeline validate-notes`.
- [x] **Deterministic schematic core**: netlist graph, functional groups, rules
  SYM-001, PIN-001/002, CAP-001, ABS-001, EQ-001, trapped project, Markdown report.

## Next

- [ ] **1. Project template**: the hardware project repo layout (`inputs/`, `design/`,
  `datasheets/`, `kicad/`, `review/`) and a `pcb-pipeline init` command.
- [ ] **2. Spec format**: JSON Schema for `design/spec.yaml` (blocks, parts and choice
  reasons, power tree, interfaces, I2C map, MCU pins, mechanical, design rules).
- [ ] **3. Phase 0**: `/define` command to run the interviewer agent, first real use to
  refine `knowledge/phase0_questions.md`.
- [ ] **4. Phase 1**: architect and component selector agents, `/architecture` command,
  datasheet download with index and manual fallback, deterministic spec checks
  (I2C conflicts, power budget, ratings), PDF rendering, PRD change impact analysis.
- [ ] **5. Datasheet agents wired**: locator, extractor, critic on 5 to 10 parts known by heart.
- [ ] **6. Working loop**: proposed fixes in findings, `review/decisions.yaml`, apply
  accepted fixes (symbol fields, values, footprints first), one commit per run.
- [ ] **7. Phase 2 complete**: `spec_conformity` checks, conformity agent, consensus,
  orchestrator, `/review` command end to end.
- [ ] **8. Learning loop**: deterministic expiry of notes (hashes of groups and files),
  `review/missed.yaml`, promotion of lessons into rules, traps
  and checklists by pull request, metrics per rule and per agent.
- [ ] **9. Test existing tools**: kicad-happy and pcbsight on a finished project; what
  they miss becomes traps.
- [ ] **10. Phase 3**: net classes and `.kicad_dru` export from the spec, DRC through
  `kicad-cli`, layout agent with pcbsight.
- [ ] **11. Footprint agent**.
- [ ] **12. HTML report**.

## Later

- [ ] Phase 4: SPICE agent (ngspice, then LTspice).
- [ ] Theorist agent and document base.
- [ ] KiCad highlight plugin (optional).
