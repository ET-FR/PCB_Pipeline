Phase 2 for this project. Read `{{pipeline}}/agents/schematic_drafter.md` and follow it, starting
from `design/spec.yaml` (signed off) and the component sheets in `{{pipeline}}/library/component_sheets`.
Draft or update the KiCad project in `kicad/` one sheet at a time, scripts in `kicad/draft/`.
Before each commit run `kicad-cli sch erc` and
`pcb-pipeline check kicad/{{name}}.kicad_sch --spec design/spec.yaml --library {{pipeline}}/library/component_sheets`.
Then run `pcb-pipeline dashboard`. $ARGUMENTS
