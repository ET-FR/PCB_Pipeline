# PCB_Pipeline

Multi-agent pipeline that helps design PCBs in KiCad faster and with fewer errors.

It follows the real design flow, from product definition to layout. At each phase it
checks the work against the datasheets and the design intent, proposes fixes, and
applies the ones the user accepts. Deterministic checks run in Python; AI agents
(driven from Claude Code) handle judgment calls. Every finding must cite its evidence:
**no proof, no finding.**

## Status

Phases 0 and 1 are built (agents, commands, deterministic spec checks, datasheet fetch,
spec rendering, change impact), as is the deterministic schematic core. Not built yet:
the fix loop, the learning loop automation, phase 2 agents end to end, phase 3. See the
[roadmap](docs/roadmap.md).

## How it works

| Phase | What happens | Output |
|---|---|---|
| 0. Definition | The user gives documents and discusses with the agent | `design/prd.md` |
| 1. Architecture | Block diagram, component selection, datasheets, power tree, interfaces, I2C map, size, design rules | `design/spec.yaml`, `design/spec.pdf`, `datasheets/` |
| 2. Schematic | The user draws in KiCad, the pipeline checks it against the spec and the datasheets | findings, report, accepted fixes |
| 3. Layout | Design rules exported to KiCad, DRC, layout review | findings, report, accepted fixes |
| 4. Simulation | Not developed yet | |

Working loop: edit in KiCad, save, run the pipeline, accept or reject each proposed
fix, the accepted ones are applied and committed. Every decision and every issue missed
by the pipeline feeds back into its rules, traps and agent checklists, so it improves
with each project.

See [docs/architecture.md](docs/architecture.md) for the full design.

## Trapped project

`tests/fixtures/buck_trapped.xml` is a small buck converter with deliberate errors
(floating EN pin, 10 V capacitor on a 12 V rail, feedback divider giving 4.44 V
instead of 5 V, MCU without MPN). Every deterministic rule must catch its trap:

```bash
pcb-pipeline check --netlist tests/fixtures/buck_trapped.xml \
  --library examples/component_sheets --rail /VIN=12 --rail /+5V=5
```

New traps are added here each time a real review misses something.

## Quick start

```bash
pip install -e ".[dev]"

# Create a hardware project repo (inputs/, design/, datasheets/, kicad/, review/)
pcb-pipeline init ../my_board

# Phase 1: validate design/spec.yaml and run the spec rules (I2C, power budget, pins, ratings)
pcb-pipeline check-spec ../my_board/design/spec.yaml
pcb-pipeline fetch-datasheets ../my_board/design/spec.yaml    # into ../my_board/datasheets/
pcb-pipeline render-spec ../my_board/design/spec.yaml         # spec.md and spec.pdf
pcb-pipeline spec-diff ../my_board/design/spec.yaml --against HEAD   # impact of a change

# Project page: status, PRD, power tree, datasheets, findings on schematic and layout
pcb-pipeline dashboard ../my_board --open

# Phase 2: schematic checks, rail voltages taken from the spec
pcb-pipeline check ../my_board/kicad/my_board.kicad_sch --spec ../my_board/design/spec.yaml

# Deterministic layer only (fast, free, runs on every commit)
pcb-pipeline check path/to/project.kicad_sch

# Same thing from an already exported KiCad XML netlist
pcb-pipeline check --netlist path/to/netlist.xml

# Validate a component sheet against the schema
pcb-pipeline validate-sheet library/component_sheets/MY-MPN.json
```

The full agent review is launched from Claude Code with the `/review` command
(see [`.claude/commands/review.md`](.claude/commands/review.md)).

## Dashboard

```bash
pcb-pipeline dashboard ../my_board --open
```

Builds `out/dashboard/index.html` in the project: phases and gates, PRD, interactive
power tree with the budget per rail, datasheet and component sheet status, findings
with clickable evidence (datasheet opened at the cited page), and the schematic and
layout exported by `kicad-cli`, with the components that have findings outlined. Click
a finding's reference to jump to the part on the schematic, then to the layout. Read
only, no AI inside: the agents run in Claude Code, the page shows their results.

## Requirements on the KiCad side

The pipeline is built and tested with **KiCad 10** (`kicad-cli` must be on the PATH, or
set `inputs.kicad_cli` in `pipeline.yaml`).

Every symbol should carry these fields, otherwise most automatic checks are impossible:

| Field | Example | Used by |
|---|---|---|
| `MPN` | `GRM188R61E106MA73` | Datasheet agent, cache key |
| `Voltage` | `25V` | Capacitor derating |
| `Tolerance` | `1%` | Divider and feedback calculations |

## Where the data lives

| Place | What |
|---|---|
| This repo | The code, and the shared knowledge that improves with every board: `knowledge/` (phase 0 questions, architecture checklist, preferred parts, accepted agent notes) and `library/component_sheets/` |
| One repo per board, created with `pcb-pipeline init ../my_board` | Everything about that board: inputs, PRD, spec and power tree, datasheet PDFs, KiCad schematic and layout, reviews, notes, dashboard |

`init` refuses to create a board inside this repo.

## Repository layout

| Path | Content |
|---|---|
| `pipeline.yaml` | Pipeline definition: phases, stages, gates, learning loop |
| `schemas/` | JSON Schemas for the spec, component sheets, findings and agent notes |
| `agents/` | Agent prompts (interviewer, architect, component selector, orchestrator, datasheet, conformity) |
| `knowledge/` | Shared knowledge that improves with use: phase 0 questions, architecture checklist, preferred parts, accepted agent notes |
| `rules/` | Deterministic rule configuration (derating, etc.) |
| `library/component_sheets/` | Shared, cached component sheets (one per MPN + revision) |
| `templates/project/` | Template of a hardware project repo, used by `pcb-pipeline init` |
| `examples/` | Example component sheet and example `spec.yaml` |
| `src/pcb_pipeline/` | Python core: KiCad import, netlist graph, rules engine, findings |
| `tests/` | Unit tests and fixtures |

## Reused tools

The pipeline deliberately builds on existing free tools rather than replacing them:
kicad-happy (deterministic layer and datasheet extraction), pcbsight (layout
measurements), ngspice and LTspice (simulation).
