# PCB_Pipeline

Multi-agent pipeline that helps design PCBs in KiCad faster and with fewer errors.

It follows the real design flow, from product definition to layout. At each phase it
checks the work against the datasheets and the design intent, proposes fixes, and
applies the ones the user accepts. Deterministic checks run in Python; AI agents
(driven from Claude Code) handle judgment calls. Every finding must cite its evidence:
**no proof, no finding.**

## Status

The deterministic schematic core works. Phases 0 and 1, the fix loop and the learning
loop are designed but not built yet: see the [roadmap](docs/roadmap.md).

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

# Deterministic layer only (fast, free, runs on every commit)
pcb-pipeline check path/to/project.kicad_sch

# Same thing from an already exported KiCad XML netlist
pcb-pipeline check --netlist path/to/netlist.xml

# Validate a component sheet against the schema
pcb-pipeline validate-sheet library/component_sheets/MY-MPN.json
```

The full agent review is launched from Claude Code with the `/review` command
(see [`.claude/commands/review.md`](.claude/commands/review.md)).

## Requirements on the KiCad side

Every symbol should carry these fields, otherwise most automatic checks are impossible:

| Field | Example | Used by |
|---|---|---|
| `MPN` | `GRM188R61E106MA73` | Datasheet agent, cache key |
| `Voltage` | `25V` | Capacitor derating |
| `Tolerance` | `1%` | Divider and feedback calculations |

## Repository layout

| Path | Content |
|---|---|
| `pipeline.yaml` | Pipeline definition: phases, stages, gates, learning loop |
| `schemas/` | JSON Schemas for component sheets and findings |
| `agents/` | Agent prompts (interviewer, orchestrator, datasheet, critic, conformity) |
| `knowledge/` | Shared knowledge that improves with use, e.g. the phase 0 question list |
| `rules/` | Deterministic rule configuration (derating, etc.) |
| `library/component_sheets/` | Shared, cached component sheets (one per MPN + revision) |
| `src/pcb_pipeline/` | Python core: KiCad import, netlist graph, rules engine, findings |
| `tests/` | Unit tests and fixtures |

## Reused tools

The pipeline deliberately builds on existing free tools rather than replacing them:
kicad-happy (deterministic layer and datasheet extraction), pcbsight (layout
measurements), ngspice and LTspice (simulation).
