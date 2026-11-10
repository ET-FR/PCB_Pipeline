# Memory rules (read by every agent)

Agents write notes while they work, so the next run does not redo the same reasoning
and does not fall into the same trap. Notes follow `schemas/notes.schema.json`.

## Where notes go

| Scope | File | Used by the next run |
|---|---|---|
| `project`: true for this board only | `review/notes.yaml` in the project repo | Directly, as long as it has not expired |
| `pipeline`: true for every project | proposed in `review/notes.yaml`, merged into `knowledge/notes.yaml` once accepted | As a hint while `proposed`, as knowledge once `accepted` |
| Something an earlier phase or run should have caught | `kind: missed` in `review/notes.yaml`, copied to `review/missed.yaml` at the end of the run | Feeds the learning loop |

Never write directly into `rules/`, `agents/`, `knowledge/phase0_questions.md` or
`library/` during a run. Those change only through a pull request the user accepts.

## Before working

1. Read the valid notes on your topic: `review/notes.yaml` (status `proposed` or
   `accepted`) and `knowledge/notes.yaml` (status `accepted`, plus `proposed` as hints).
2. A note is valid only if everything in `depends_on` is unchanged (same sheet revision,
   same spec revision, same group hash, same file hashes). Otherwise mark it `expired`
   and redo the work.
3. Skip what a valid `verified` note already covers, and say so in your output
   ("C4 derating already verified, note N-20261110-004"). Never skip a check on a
   `power` or `mains` group during a pre-fabrication gate: notes speed up iterations,
   not the final review.
4. Look for every `pitfall` and `datasheet_quirk` note that applies to your parts.

## While working

Write a note when you:
- finish a check that took real reasoning and passed (`verified`)
- record a choice made with the user and its reason (`decision`)
- find a trap that could catch someone again (`pitfall`)
- find where a piece of information hides in a datasheet (`shortcut`)
- find an error, an ambiguity or a contradiction in a datasheet (`datasheet_quirk`)
- notice that a phase 0 question was missing (`question`)
- notice that an earlier phase or run should have caught a problem (`missed`)

Rules:
- **No proof, no note.** Every note has evidence: datasheet page, net, calculation,
  spec entry, or the user's words.
- `verified` and `decision` notes must have `depends_on`, so they expire when their
  inputs change.
- One fact per note, one or two sentences. Write what the next run can take as known,
  not your whole reasoning.
- Prefer `project` scope. Use `pipeline` only for what is true whatever the board.

## End of run

The orchestrator lists the new `pipeline` notes and `missed` entries for the user, who
accepts or rejects each one. Accepted pipeline notes are merged by pull request into
`knowledge/notes.yaml`, or turned into a rule, a trap, a checklist item or a phase 0
question when that fits better (`promoted_to` records where it went).
