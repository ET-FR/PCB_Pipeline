Phase 3 for this project. Read `{{pipeline}}/agents/layout.md` and follow it, starting from
`design/spec.yaml`, the signed-off schematic in `kicad/` and `review/gates.yaml`.
Create the board once with `pcb-pipeline layout-init`; after each placement or routing round run
`pcb-pipeline layout-check` and review `out/layout/layout_report.md`.
Then run `pcb-pipeline dashboard`. $ARGUMENTS
