---
name: token-police
description: Inspect agent usage, evaluate cost controls, and turn recurring deterministic waste into scripts. Use for an explicit usage audit or a flagged exception. Do not invoke for every task or routine monitoring.
---
Run the bundled `../../scripts/tp.py` from this skill directory, or locate `scripts/tp.py` at the plugin root. Execute with Python 3.10+. Do not read source or full logs unless debugging requires it.
1. Run `doctor`, then `status`. Report missing instrumentation before saying there is no waste. Review only the highest priority relevant finding. A `repeatable_action` finding does not create a skill.
2. For measurement, use `ingest`, `summary`, `report`, and `reconcile`. Scripts perform all arithmetic. Read `../../docs/accounting.md` only for formats. Never guess missing usage, prices, acceptance, or overhead. Never claim savings from a shorter reply.
3. For a repeated check, run the script instead of pasting a one-liner: `gate-exit` for an exit code, `diffstat` for a capped path list, `secret-names` for filenames only, `skill-budget` for a word count.
4. Judgment stays with the task owner: lane choice, small fix versus blocked, model escalation, and whether to wake another bot. Use `skill-eval` before drafting a skill. A deterministic repeat stays a script. `skill-eval` never creates the file.
5. Apply only configured limits. Preserve native permissions. No polling, auditor agents, or automatic model wakes. A tool hook cannot see another bot's chats or profiles.
Keep responses short. Do not mark a task accepted without the owner's evidence. For budgets and collection, read `../../docs/operations.md` only when a governed command is required.
For reference pagination, continue with both `next_offset` and `next_byte_offset` until complete. Use `--force` after context loss when lifecycle hooks were unavailable.


For cross-agent reuse, record explicit operation receipts with `activity-record`, then run `reuse-scan` and `reuse-draft` with the project and scope. Drafts use reviewed script templates; unknown operations need a reviewed recipe. Review hashes with `reuse-state --state approved` before host installation. See `../../docs/reuse.md`. Never skip required checks based on repetition.
