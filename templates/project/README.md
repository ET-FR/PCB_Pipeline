# {{name}}

Hardware project designed with [PCB_Pipeline](https://github.com/ET-FR/PCB_Pipeline).

| Phase | Command in Claude Code | Output |
|---|---|---|
| 0. Definition | `/define` | `design/prd.md` |
| 1. Architecture | `/architecture` | `design/spec.yaml`, `design/spec.pdf`, `datasheets/` |
| 2. Schematic | `/review` | `review/<run>/` |
| 3. Layout | `/review` | `review/<run>/` |

Working loop: edit in KiCad, save, run the command, accept or reject each proposed fix.

## Layout

| Path | Content |
|---|---|
| `inputs/` | Documents for phase 0 (specs, notes, sketches, reference designs) |
| `design/` | `prd.md`, `spec.yaml`, generated `spec.pdf` |
| `datasheets/` | Local PDFs (not committed) and `index.yaml` (committed) |
| `kicad/` | The KiCad project |
| `review/` | Review runs, `decisions.yaml`, `missed.yaml`, `notes.yaml` |
