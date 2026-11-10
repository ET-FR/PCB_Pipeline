# Roadmap

Ordered by value: the earlier phases catch the most expensive errors.

## Done

- [x] **Foundations**: repo structure, `pipeline.yaml`, `kicad-cli` import, pre-commit hook.
- [x] **Formats (first draft)**: JSON Schemas for component sheets and findings.
- [x] **Phase 0 question list** (`knowledge/phase0_questions.md`) and interviewer prompt.
- [x] **Agent memory format**: `schemas/notes.schema.json`, `agents/memory.md`,
  `pcb-pipeline validate-notes`.
- [x] **Project template**: `templates/project/` and `pcb-pipeline init`.
- [x] **Spec format**: `schemas/spec.schema.json`, example `examples/spec/sensor_node.spec.yaml`.
- [x] **Deterministic spec checks**: `pcb-pipeline check-spec` (SPEC-001 references,
  BUS-001/002 I2C addresses, MCU-001 pins, PWR-001 to PWR-005 power budget, voltages,
  LDO dissipation), trapped spec, rail voltages from the spec for schematic checks.
- [x] **Deterministic schematic core**: netlist graph, functional groups, rules
  SYM-001, PIN-001/002, CAP-001, ABS-001, EQ-001, trapped project, Markdown report.

## Next

- [ ] **3. Phase 0 first real use**: run `/define` on a real board, refine
  `knowledge/phase0_questions.md`.
- [ ] **4. Phase 1**: architect and component selector agents, `/architecture` command,
  datasheet download with index and manual fallback, part ratings versus component
  sheets (regulator input range, absolute max), PDF rendering, PRD change impact analysis.
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
