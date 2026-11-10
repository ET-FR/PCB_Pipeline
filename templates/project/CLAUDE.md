# Instructions for Claude Code

This is the hardware project `{{name}}`, designed with PCB_Pipeline.

- Pipeline repo (code, read only from here): `{{pipeline}}`. Agent prompts are in
  `{{pipeline}}/agents/`, rules in `{{pipeline}}/rules/`.
- Knowledge base (your shared data): `{{data_home}}`. Component sheets in
  `{{data_home}}/library/component_sheets/`, knowledge in `{{data_home}}/knowledge/`.
  Run `pcb-pipeline where` if a path has moved.
- This board's data stays in this repo. Never write board data into the pipeline repo;
  only reusable knowledge goes to the knowledge base, after the user accepts it.
- Write everything in this repo in English. Talk to the user in French.
- `design/spec.yaml` is the reference for design intent. Validate it with
  `pcb-pipeline check-spec design/spec.yaml` after every change.
- Never edit files in `kicad/` without the user's explicit agreement on each change,
  and only with a clean git tree, so every change is one revertable commit.
- Follow `{{pipeline}}/agents/memory.md`: read `review/notes.yaml` before working,
  write notes while working.
- When something should have been caught earlier, add it to `review/missed.yaml`.
- The project uses KiCad 10. After every run, regenerate the dashboard with
  `pcb-pipeline dashboard` (output in `out/dashboard/index.html`).
- When the user signs a phase off, add the gate to `review/gates.yaml`.
