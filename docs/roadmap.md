# Roadmap

- [ ] **1. Foundations**: repo structure, `pipeline.yaml`, `kicad-cli` import, pre-commit hook.
- [ ] **2. Test existing tools**: run kicad-happy and pcbsight on a finished project, note what they find and what they miss. Use the misses as seed requirements and as the "trapped project" test suite.
- [ ] **3. Formats**: JSON Schemas for component sheets and `findings.json`, aligned with kicad-happy outputs; MPN and Voltage fields in all symbols.
- [ ] **4. Datasheet and Conformity agents** on top of kicad-happy extraction, plus the rule checklist. First test on 5 to 10 parts known by heart.
- [ ] **5. Critic, multi-run consensus and trapped project**, benchmark against Traceformer.
- [ ] **6. Footprint agent**: parse `.kicad_mod`, compare to land pattern.
- [ ] **7. SPICE agent**: simple subcircuits with ngspice, then LTspice for converters.
- [ ] **8. Layout agent** with pcbsight measurements and per-layer renders.
- [ ] **9. Theorist agent** and document base.
- [ ] **10. HTML report, `/review` command, pull request review.**
- [ ] **11. KiCad highlight plugin** (optional).
