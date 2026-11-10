# PCB_Pipeline knowledge base

Your own data, shared by all your boards and improved with every project. Created by
`pcb-pipeline setup`. Keep it in its own private git repo: it is not part of the
pipeline code, and it is not part of any single board.

| Path | Content | Updated by |
|---|---|---|
| `library/component_sheets/` | One JSON sheet per MPN and datasheet revision, built from the datasheets | Datasheet agents, validated by you |
| `knowledge/phase0_questions.md` | Questions and data the interviewer needs, with your defaults | Interviewer proposals, missed issues |
| `knowledge/architecture_checklist.md` | What every architecture must answer | Architect proposals, missed issues |
| `knowledge/preferred_parts.yaml` | Parts you trust, proposed first | Component selector proposals |
| `knowledge/notes.yaml` | Accepted pipeline notes: datasheet quirks, pitfalls, shortcuts | Agent notes you accept |

Every change is proposed by an agent and accepted by you; commit it here.
Find this folder with `pcb-pipeline where`.
