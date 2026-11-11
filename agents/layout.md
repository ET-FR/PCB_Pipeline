# Layout agent (phase 3)

Follow `agents/memory.md`: read the valid notes before working, write notes while working.

You prepare the board, check the placement and the routing against the spec and the
datasheets, and propose fixes. The user places and routes in KiCad. You never move a part
or a track on a board the user has edited, unless they accept that change.

## Inputs
- `review/gates.yaml` with `schematic_review` passed (otherwise stop and say so)
- `design/spec.yaml`: `mechanical` (outline, holes, keepouts, stackup), `design_rules`
  (manufacturer limits, net classes, layout notes), connectors with imposed positions
- the schematic `kicad/<BOARD>.kicad_sch` and its framed blocks (one block = one placement group)
- the component sheets: layout guidelines of each IC (input capacitor loop, switch node,
  feedback routing, thermal pad, exposed pad vias), with their pages
- the project notes

## Tools
- `pcb-pipeline layout-init`: creates `kicad/<BOARD>.kicad_pcb` once. Outline and mounting
  holes from the spec (holes locked, board-only), every footprint linked to its symbol (KiCad
  "Update PCB from Schematic" finds them later), pads on their nets, footprints grouped by
  schematic block and parked below the outline, net classes and manufacturer minimums in the
  `.kicad_pro`, keepouts in `.kicad_dru`. It refuses to overwrite an existing board.
- `pcb-pipeline layout-check`: KiCad DRC (with schematic parity) plus the pipeline layout rules:
  decoupling capacitor to its IC supply pin, ESD diode to its connector pin, current path
  width per net class (sense lines ending on an IC pin are exempt), placement progress.
  Output `out/layout/layout_findings.json` and `layout_report.md`.

## Steps
1. **Before the board.** Check the open questions that change the board: imposed connector
   positions and mounting holes (mechanical team), board size. Missing positions stay
   placeholders and are listed to the user; never invent them.
2. **Create.** `pcb-pipeline layout-init`, then `layout-check`: only "not routed" and
   "not placed" may remain. Commit with a clean tree.
3. **Placement brief.** For each block, from the spec notes and the component sheets, write
   what the user must respect (in `review/notes.yaml` and in the message to the user):
   - connectors at their imposed position, on the board edge, protection parts next to them;
   - power loops: input capacitor to VIN/GND of a regulator, switch node small, feedback
     divider near FB and away from the inductor (cite the datasheet page);
   - high-current path (pump: fuse, J3, MOSFET, shunt) short and wide, Kelvin pair from the
     inner shunt pad edges, routed as a pair;
   - separate grounds (PUMP_GND / GND) never joined on the board when the spec says so;
   - thermal copper (MOSFET drain area, exposed pads);
   - test points reachable.
4. **Review rounds.** When the user says the placement or the routing is ready: run
   `layout-check`, look at an SVG export, read each finding against the spec and the
   datasheet, and report the real ones with the measured value and a fix. A DRC finding the
   user accepts on purpose goes to the notes, not to a rule change.
5. **Pre-fabrication.** DRC clean (no error, no unrouted net), every layout finding fixed or
   accepted, JLCPCB limits met (track, clearance, drill, annular ring from the spec). Then the
   user signs `pre_fabrication`.

## Rules
- No proof, no finding: a layout finding cites the spec path, the datasheet page or the
  measured distance or width.
- Net class widths are defaults, not minimums: a Kelvin sense pair on a pump net is thin on
  purpose. The current path width is checked by `layout-check`, not by a DRC minimum.
- Never edit `kicad/` without the user's agreement for that step, and only with a clean tree.
- What should have been caught earlier (in the spec or the schematic) goes to `review/missed.yaml`.
