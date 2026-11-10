Phase 1 for this project. Read `{{pipeline}}/agents/architect.md` and follow it, starting
from `design/prd.md`, `{{pipeline}}/knowledge/architecture_checklist.md` and
`{{pipeline}}/knowledge/preferred_parts.yaml`.
Write `design/spec.yaml`. After every change run
`pcb-pipeline check-spec design/spec.yaml --library {{pipeline}}/library/component_sheets`.
At the end run `pcb-pipeline render-spec design/spec.yaml`. $ARGUMENTS
