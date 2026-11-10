# Instructions for Claude Code

This is the hardware project `{{name}}`, designed with PCB_Pipeline.

- Pipeline repo: `{{pipeline}}`. Agent prompts are in `{{pipeline}}/agents/`, shared
  knowledge in `{{pipeline}}/knowledge/`, rules in `{{pipeline}}/rules/`.
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
