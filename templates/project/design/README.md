# Design

- `prd.md`: product requirements, written in phase 0 (`/define`).
- `spec.yaml`: architecture and design rules, written in phase 1 (`/architecture`).
  Format: `schemas/spec.schema.json` in the pipeline repo, example in
  `examples/spec/sensor_node.spec.yaml`.
- `spec.md` and `spec.pdf`: generated from `spec.yaml` by `pcb-pipeline render-spec`,
  never edited by hand.

Useful commands:

```bash
pcb-pipeline check-spec design/spec.yaml          # schema, power budget, I2C, pins, ratings
pcb-pipeline fetch-datasheets design/spec.yaml    # download PDFs, update datasheets/index.yaml
pcb-pipeline render-spec design/spec.yaml         # spec.md and spec.pdf
pcb-pipeline spec-diff design/spec.yaml --against <git rev>   # impact of a change
```
