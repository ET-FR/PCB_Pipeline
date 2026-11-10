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
1. **Project.** Create `kicad/<BOARD>.kicad_pro`. Choose the page structure (layout rules 1
   and 4 below): a small board (about 100 parts or less) goes on one page, `Project.page()`,
   A3 if needed, with one cluster per spec block and a short title over each cluster. A larger
   board gets a root sheet holding every connector, plus one hierarchical sheet per function
   (not per IC), `Project.sheet()`.
2. **Symbols.** Use the KiCad library symbol when it exists and its pin numbers match the
   component sheet. Otherwise create it in the project library `kicad/<BOARD>.kicad_sym` from
   the component sheet (pin names and numbers exactly as in the datasheet), with the supply
   pins on top and the ground pins at the bottom, and say so.
3. **One block at a time.** For each block: the parts of the spec, the external parts of the
   component sheet application circuit (with the values and the page they come from), the
   nets named as in the spec (rails, connector nets, bus nets). Fill `MPN` on every part,
   `Voltage` on every capacitor, `LCSC` when known, and a JLCPCB-compatible footprint. Show
   short values (`100nF`, `4.7k`); tolerance, voltage and dielectric go in hidden fields.
   Place the parts by function (input on the left, output on the right, feedback below).
4. **Check before the commit.** `Project.save()` then `Project.issues()` must be empty (no
   overlap, nothing on the page frame or the title block). Then `kicad-cli sch erc` and
   `pcb-pipeline check <sch> --spec design/spec.yaml`. Fix what is yours. Add `PWR_FLAG` on
   rails that come from a connector or through a passive part (fuse, inductor, filter).
   Look at an SVG export of the page: the overlap check is an approximation.
5. **Commit** with a clean tree, then tell the user what is ready to review. Never edit
   `kicad/` without the user's agreement for that step.
6. **Later changes.** Never regenerate a page the user has edited: load it, change only what
   is needed (add, remove or re-value a part, change a net), save, re-run step 4. Positions
   set by the user are kept.

## Layout rules (from the user, FRONT_BOARD review, 2026-11-10)
1. **Connectors on the main page.** On a hierarchical design, every connector sits on the
   root page and reaches the block sheets through hierarchical sheet pins (input, output,
   bidirectional, passive), not through global labels hidden inside the sheets.
2. **Power symbols always vertical.** Rails point up, grounds point down (pointing away from
   the part on a vertical stub). Never a sideways power symbol. On a crowded connector or IC
   side, draw the rail as a global label of the same name instead (`labels=` in `pins()`);
   a net drawn once as a global label is then global everywhere (the module does it).
3. **No overlap.** Labels, references, values, texts, net names and symbol bodies never
   overlap each other, the page frame or the title block. `Project.issues()` checks it;
   KiCad text is about 1.17 mm per character at 1.27 mm size.
4. **No sheet per IC.** A project this small fits on one page; split into sheets only when a
   page would be unreadable, and then by function.
5. **Compact.** 100 mil (2.54 mm) between items is enough as long as nothing overlaps: short
   wire stubs (2.54 mm), parts in clusters, no large empty areas.

## Rules
- A value without a source is not drafted: it comes from a component sheet (with its page),
  the spec, a calculation by the pipeline, or the user. Unknown values are written `TBD`
  and listed in the commit message.
- Net names in the schematic match the spec (`/NET` in the spec is `NET` on a power symbol
  or global label).
- kicad-sch-api 0.5.x pitfalls handled by the module: wrong pin positions on rotated parts,
  global labels not written, a visible `hierarchy_path` property, a stray wire on the root
  sheet, local labels always justified left (drawn over the pin at 180/270 degrees), field
  angles of rotated symbols (KiCad adds the symbol rotation). Do not work around the module;
  fix it in the pipeline and add a test.
- A local label does not join a power net of the same name; a global label does.
