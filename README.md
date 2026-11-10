# PCB_Pipeline

Multi-agent design review pipeline for KiCad hardware projects.

The pipeline reads a KiCad project, builds a structured component sheet for every
part from its datasheet, then checks the schematic against those sheets. Deterministic
checks run in Python; AI agents (driven from Claude Code) handle judgment calls.
Every finding must cite its evidence: **no proof, no finding.**

## Status

Step 1 of the [roadmap](docs/roadmap.md): foundations, data formats, deterministic core.
Agents are defined (prompts in [`agents/`](agents/)) but not yet wired to an orchestrator.

## How it works

```
KiCad project ──kicad-cli──> netlist + BOM ──> netlist graph ──> functional groups
                                                     │
MPN list ──> Datasheet agent ──> component sheets ───┤
             (locate > extract > critique)           │
                                                     v
                         Deterministic rules + Conformity agent
                                                     │
                                                     v
                              findings.json ──> report (Markdown / HTML)
```

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
| `pipeline.yaml` | Pipeline definition: stages, triggers, thresholds |
| `schemas/` | JSON Schemas for component sheets and findings |
| `agents/` | Agent prompts (orchestrator, datasheet, critic, conformity) |
| `rules/` | Deterministic rule configuration (derating, etc.) |
| `library/component_sheets/` | Shared, cached component sheets (one per MPN + revision) |
| `src/pcb_pipeline/` | Python core: KiCad import, netlist graph, rules engine, findings |
| `tests/` | Unit tests and fixtures |

## Reused tools

The pipeline deliberately builds on existing free tools rather than replacing them:
kicad-happy (deterministic layer and datasheet extraction), pcbsight (layout
measurements), ngspice and LTspice (simulation).
