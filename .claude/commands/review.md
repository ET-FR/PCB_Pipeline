Run a design review of the board repo at: $ARGUMENTS

All board outputs go to the board repo, never to this repo. With BOARD the path above:

1. Run `pcb-pipeline check-spec BOARD/design/spec.yaml --out BOARD/out/` and
   `pcb-pipeline check BOARD/kicad/<name>.kicad_sch --spec BOARD/design/spec.yaml --out BOARD/out/`.
2. Read `agents/orchestrator.md` and follow it, using the outputs in `BOARD/out/`.
3. Write `BOARD/out/findings.json`, validate it, then run `pcb-pipeline report BOARD/out/findings.json`.
4. Summarize the critical and major findings in the terminal, with their evidence.
5. Run `pcb-pipeline dashboard BOARD`.
