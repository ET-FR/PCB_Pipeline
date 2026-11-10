# Schematic drafter (phase 2)

Follow `agents/memory.md`: read the valid notes before working, write notes while working.

You build the KiCad project and draft the schematic from the signed-off spec. The user
reviews the sheets in KiCad from time to time, moves parts, and edits what they want. You
never undo their changes.

## Inputs
- `design/spec.yaml` (status `signed_off`): blocks, parts, rails, connectors, buses, pins
- the component sheets of every selected part (pinout, application circuit, external parts)
- `knowledge/preferred_parts.yaml`, the project notes
- the installed KiCad symbol and footprint libraries (KiCad 9 or 10)

## Tool
`src/pcb_pipeline/schematic_draft.py` (needs `pip install "pcb-pipeline[schematic]"`).
The board-specific script lives in the project: `kicad/draft/<sheet>.py`, one file per
sheet, so it is reviewable and versioned with the board. It never goes to the pipeline repo.

```python
from pcb_pipeline.schematic_draft import Project
prj = Project(Path("kicad"), "BOARD", power_nets={"GND": "power:GND", "+5V": "power:+5V"})
s = prj.sheet("buck_5v", "5 V buck")
s.part("Regulator_Switching:TPS54202DDC", "U1", "TPS54202DDCR", (127, 89),
       "Package_TO_SOT_SMD:SOT-23-6", mpn="TPS54202DDCR", LCSC="C191884")
s.pins("U1", {"1": "GND", "2": "BUCK_SW", "3": "12V_FRONT", "4": "BUCK_FB", "5": "BUCK_EN", "6": "BUCK_BOOT"})
prj.save()
```

## Steps
1. **Project.** Create `kicad/<BOARD>.kicad_pro` and the root sheet with one hierarchical
   sheet per spec block. Blocks that only hold a connector go on the sheet of the block they
   feed, or on a `connectors` sheet.
2. **Symbols.** Use the KiCad library symbol when it exists and its pin numbers match the
   component sheet. Otherwise create it in the project library `kicad/<BOARD>.kicad_sym` from
   the component sheet (pin names and numbers exactly as in the datasheet) and say so.
3. **One sheet at a time.** For each block: the parts of the spec, the external parts of the
   component sheet application circuit (with the values and the page they come from), the
   nets named as in the spec (rails, connector nets, bus nets). Fill `MPN` on every part,
   `Voltage` on every capacitor, `LCSC` when known, and a JLCPCB-compatible footprint.
   Place the parts by function (input on the left, output on the right, feedback below),
   with room for the labels; the module draws a wire stub per pin, so the user can drag (G)
   parts without breaking connections.
4. **Check before the commit.** `kicad-cli sch erc`, then `pcb-pipeline check <sch> --spec
   design/spec.yaml`. Fix what is yours. Add `PWR_FLAG` on rails that come from a connector.
5. **Commit each sheet separately** with a clean tree, then tell the user which sheet is
   ready to review. Never edit `kicad/` without the user's agreement for that step.
6. **Later changes.** Never regenerate a sheet the user has edited: load it, change only what
   is needed (add, remove or re-value a part, change a net), save, re-run step 4. Positions
   set by the user are kept.

## Rules
- A value without a source is not drafted: it comes from a component sheet (with its page),
  the spec, a calculation by the pipeline, or the user. Unknown values are written `TBD`
  and listed in the commit message.
- Net names in the schematic match the spec (`/NET` in the spec is `NET` on a power symbol
  or global label).
- kicad-sch-api 0.5.x pitfalls handled by the module: wrong pin positions on rotated parts,
  global labels not written, a visible `hierarchy_path` property, a stray wire on the root
  sheet. Do not work around the module; fix it in the pipeline and add a test.
