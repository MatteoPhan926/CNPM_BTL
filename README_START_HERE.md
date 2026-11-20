# Smart E-Mobility Hub — A/B/C Implementation Workspace

This is a **Codex-ready starting workspace** for implementing the A/B/C MVP. It is not a completed application. At packaging time it contains a 14-screen static UI prototype and the existing academic specifications/design artifacts; it contains **no known working backend or runnable end-to-end business flows**.

## Start (Windows PowerShell)

1. Extract `Smart_EMobility_ABC_Codex_Workspace.zip` into a writable folder (e.g. `E:\Downloads\Smart_EMobility_ABC_Codex_Workspace`). Keep the directory structure.
2. Open PowerShell in that extracted folder.
3. Start `codex` (or `codex --no-daemon` if needed for your local installation).
4. Give Codex this request:

   > Read `CODEX_TASK.md` and `AGENTS.md`, inspect the workspace independently, and execute the A/B/C implementation task end-to-end. Implement and verify working software, not just a plan.

You may instead paste the contents of `CODEX_TASK.md` directly into Codex.

## Files included

| Path | Purpose |
|---|---|
| `prototype/smart-emobility-clean-ui.html` | Original 14-screen UI reference; **mock/prototype**, not working application |
| `docs/01_requirements/00_course_project_brief.pdf` | Original broad course project brief |
| `docs/01_requirements/01_assignment_1_submitted.pdf` | Submitted requirements, use cases, business rules |
| `docs/01_requirements/02_assignment_2_submitted.pdf` | Submitted activities, UI and sequence behavior |
| `docs/01_requirements/03_assignment_3_submitted.pdf` | Submitted team report: architecture, class diagrams, method descriptions and planned tests |
| `docs/01_requirements/*.txt` | Text extracted from same PDFs, useful for search; images, diagrams and layout must be checked in PDFs |
| `docs/02_design/mermaid_v4/` | 14 Mermaid architecture, role and cross-role diagrams; **design references**, not deployed code |
| `docs/02_design/audit_reference/` | Historical consistency audit, traceability and contracts; not test results for an implemented MVP |
| `CODEX_TASK.md` | Current coding task |
| `AGENTS.md` | Short non-prescriptive scope/safety guidance |

## Source interpretation

- The **course brief** defines the broad assignment.
- **Assignment 1** and **Assignment 2** are submitted requirements and behavior baselines; don't silently rewrite their meaning.
- **Assignment 3** is the submitted design intent. If it conflicts with earlier behavior, investigate, document and resolve deliberately.
- Mermaid v4 and the audit files are supplementary implementation guidance and may differ from the later submitted PDF. Inspect actual evidence, not just file timestamps.
- Role D is **not** part of the current implementation target. Keep integration boundaries explicit, and never report a physically verified action based solely on a mock UI click.

## Scope

Implement and validate UC-A01–A07, UC-B01–B05 and UC-C01–C03, including their interactions. Do not mark Role D (UC-D01–D07) implemented unless separately authorized and actually built. No framework or architecture has been preselected by this package.

## Before claiming completion

Provide a runnable system, instructions and executable tests, and explicitly distinguish implemented behavior, controlled simulation and remaining unimplemented dependencies. Preserve the original prototype/specifications as evidence; new application code can live wherever the architecture merits.
