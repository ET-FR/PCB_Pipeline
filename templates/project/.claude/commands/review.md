Review this project. Run `pcb-pipeline check-spec design/spec.yaml --out out/`, then
`pcb-pipeline check kicad/{{name}}.kicad_sch --spec design/spec.yaml --out out/`.
Read `{{pipeline}}/agents/orchestrator.md` and follow it with the outputs in `out/`.
For every finding, propose a fix and ask the user to accept, reject or defer it.
Record decisions in `review/decisions.yaml`, apply accepted fixes in one commit.
Finally run `pcb-pipeline dashboard` and tell the user to refresh `out/dashboard/index.html`. $ARGUMENTS
