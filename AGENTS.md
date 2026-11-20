# Workspace guidance for coding agents

- Goal: deliver a runnable and meaningfully tested **A/B/C** MVP for Smart E-Mobility Hub, not another planning-only artifact.
- Independently inspect all existing evidence and choose implementation architecture based on demonstrated requirements and constraints.
- Read `CODEX_TASK.md`. Submitted specs are evidence; distinguish business requirements, proposed design, UI mockups and actual executable software.
- Keep original PDFs and original HTML prototype available as reference. If adapting the UI, preserve a traceable original.
- Work within A/B/C; make the dependency on Role D explicit. Never fabricate physical verification, IoT acknowledgments or tests that did not run.
- Validate cross-role behavior, concurrency/idempotency, failures and access control, with reproducible automated checks where feasible.
- Use independent review/subagents when beneficial; challenge apparent design contradictions rather than blindly following prior choices.
- End with reproducible run/test instructions and an evidence-backed implementation/limitations summary.
