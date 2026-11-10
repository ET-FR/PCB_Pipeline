Run a design review of the KiCad project at: $ARGUMENTS

1. Run `pcb-pipeline check $ARGUMENTS --out out/` (import, graph, deterministic rules).
2. Read `agents/orchestrator.md` and follow it, using the outputs in `out/`.
3. Write `out/findings.json`, validate it, then run `pcb-pipeline report out/findings.json`.
4. Summarize the critical and major findings in the terminal, with their evidence.
