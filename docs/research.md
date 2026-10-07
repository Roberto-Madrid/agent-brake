# Research and standards mapping

Reviewed primary project documentation on 2026-10-07. These are design references, not endorsements, vendored code, benchmarks, or interoperability certifications. Tool behavior and installation details can change.

| Reference | Relevant approach | AgentBrake decision |
|---|---|---|
| [RTK](https://github.com/rtk-ai/rtk) | Deterministic CLI output reduction | Prefer small scripts and bounded output; leave general command compression to existing tools. Output reduction is not automatically equivalent to invoice savings. |
| [Token Economy Kit](https://github.com/dani-lore/token-economy-kit) | Targeted Claude hooks and on-demand skills | Keep host adapters thin and skills concise; do not couple core policy to a particular model. |
| [AgentBudget](https://github.com/AgentBudget/agentbudget) | Application-side budget enforcement | Preserve explicit usage receipts and atomic admissions; do not duplicate provider SDK instrumentation. |
| [Cycles Claude plugin](https://github.com/runcycles/cycles-claude-plugin) | Reservation and settlement around tool actions | Keep idempotent action accounting and distinguish estimated action cost from final token usage. Distributed authority remains external. |
| [TokenPolice](https://tokenpolice.ai/docs/get-started/coding-agent/overview) | Coding-agent assistance for application SDK integration | Distinguish app spend instrumentation from cross-agent procedure discovery; similar naming does not establish equivalent capabilities. |
| [Agent Skills specification](https://agentskills.io/specification) | `SKILL.md` metadata, instructions, and optional scripts/references | Generated skills use name/description frontmatter and script delegation. Installation and runtime permissions remain host-specific. |
| [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/) | Standardized telemetry naming | Existing adapter accepts supported flattened GenAI attributes. Do not claim full OTLP transport or every evolving GenAI convention. |

## Engineering practices applied

- Dependency-free deterministic runtime; provider-specific ingestion is separate from policy.
- Explicit identities, versioned receipt contracts, exact matching, and scoped aggregation.
- Idempotency conflicts fail visibly; local concurrent writes use SQLite transactions.
- Observe-by-default controls, native permissions, explicit ownership, and managed roles.
- Script templates rather than executing logs; hashes and exact file-set validation at approval.
- Progressive disclosure in skills; raw prompts and secret values are unnecessary for reuse detection.
- Separate estimated, billed, and unknown cost; evaluate accepted outcomes instead of token count alone.
- Documented failure boundaries, audit records, reproducible distribution tooling, and regression checks.

These are selected applicable standards and engineering practices. “All industry standards” is not a finite or verifiable target. This repository does not claim SOC 2, ISO 27001, formal security certification, distributed consensus, or production effectiveness without a deployment-specific assessment.
