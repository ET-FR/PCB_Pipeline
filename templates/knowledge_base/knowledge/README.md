# Knowledge

Shared knowledge that the agents read and that improves with every project.

| File | Content | Updated by |
|---|---|---|
| `phase0_questions.md` | Questions and data the interviewer needs for a good PRD | Interviewer proposals, missed issues |
| `architecture_checklist.md` | What every architecture must answer before the schematic | Architect proposals, missed issues |
| `preferred_parts.yaml` | Parts the user already trusts, proposed first | Component selector proposals |
| `notes.yaml` | Accepted pipeline notes: datasheet quirks, pitfalls, shortcuts true for every project | Agent notes accepted by the user (see `agents/memory.md`) |

Project-specific memory stays in the board repo (`review/notes.yaml`).
Every change to this folder is proposed by an agent and committed once the user accepts it.
The seed versions live in the pipeline repo (`templates/knowledge_base/`); this copy is yours.
