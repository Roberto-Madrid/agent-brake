# Token Police: pending work and enterprise roadmap

Status: v0.3 private pilot. See release.md and validation.md for current packaging checks. The v0.2 tables below are historical; local tests and manifests still do not establish live coverage, savings, or enterprise readiness.

## Product goal

Reduce total cost per accepted agent task without increasing defects, delays, or human supervision. Include Token Police's own implementation, execution, review, and maintenance costs. Lower token counts alone are not success.

Keep measurement and routine enforcement deterministic. Invoke a model only for a bounded exception that requires judgment. Task owners retain strategy and architecture decisions.

## What is implemented, tested, and still unverified

"In code" means the local Python package contains the behavior. "Local tests" means `python3 -m unittest discover -s tests` exercises it with fixtures. Neither column is a live host, a provider bill, or a savings result.

| Capability | In code | Local tests | Still unverified |
| --- | --- | --- | --- |
| Incremental import, immutable IDs, duplicate protection, missing-cost holds | Yes | Yes | Provider reconciliation and export gaps |
| OpenAI, Anthropic, and Claude final-receipt adapters | Yes | Fixture tests. Omitted cache fields are still treated as zero | One real export per provider and version |
| Flattened OTel spans | Yes | Yes: known cost without tokens, unknown cache not priced, envelopes, batches, aggregate spans, separate retry spans | A real collector export |
| Workflow reserve, callback, and settle | Yes | Yes, including replay and failed callbacks | A production runner and its retries |
| Task, project, and governor admissions; review cooldowns | Yes | Yes: shared governor cap, release frees allowance, governor spend counts toward the project, worker spend does not consume the governor cap | Fleet enforcement outside this process |
| Collect and collect/evaluate cycle | Yes | Yes: missing source, bad-batch rollback, identity mismatch, disable only with complete evidence and apply | A scheduled job on real traffic |
| Versioned rules, exceptions, interventions, harmful-control disable | Yes | Yes | A control retained or rolled back on real work |
| Bounded output, Claude read limits, references, JSON selection, cache report | Yes | Yes | Claude and Codex installs |
| Repeated gates (`gate-exit`, `diffstat`, `secret-names`, `skill-budget`) and advisory `repeatable_action` findings | Yes | Yes. The finding does not create a skill, and the checks do not claim savings | Live host hooks, skill-load evidence, and a measured bill |
| Organization policy, OS roles, audit chain, retention | Yes | Yes, including a looser local policy at the launcher | Hostile-client tampering and Windows ACLs |
| Claude/OpenAI plugin packaging and CI configuration | Yes | Local package validator | Remote CI, official host validators, marketplace review |

These local capabilities do not intercept every agent, reconcile every bill, establish real savings, or provide a hostile-client security boundary.

## Immediate pending work

| Priority | Work | Where it stands |
| --- | --- | --- |
| P0 | Targeted tests for the newest adapters, collection/evaluation, policy enforcement, and governor budgets | Local tests and the operations contract now cover this. 76 tests passed on 2026-09-29 |
| P0 | Install on actual Claude and compatible OpenAI runtimes | Blocked. `claude` is not installed. No Codex or ChatGPT Work CLI is installed |
| P0 | Integrate one real recurring workflow | Local stand-in only: `run` executes the unit tests and records no model receipt. A runner that emits final usage, retries, child requests, outcomes, and governor overhead is still required |
| P0 | Run baseline and treatment on comparable normal work | Not run. The local stand-in compare returns `insufficient_evidence` and null savings |
| P0 | Reconcile usage against provider records | Blocked. No usage export and no provider credential are available. Unresolved charges stay unknown |
| P0 | Deployment boundary for administrator policy | Local launcher test: a looser local policy file cannot raise the organization read limit or drop enforce mode. Secrets handling and a protected deployment are not verified |
| P1 | Exercise Windows/macOS and clean installation | Not run. Remote CI has not run |
| P1 | Publish a reproducible release | Not started. No marketplace listing and no release publication |

The first pilot should change one control at a time. Do not spend money duplicating every task solely to demonstrate savings.

## Enterprise enhancements, in order

### 1. Reliable integration and coverage

Integrate with the company's existing agent runner and telemetry pipeline. Reuse existing instrumentation where it is sufficient. Track request ancestry, workflow version, policy version, model, pricing basis, retries, and final outcomes.

Display coverage explicitly: registered tasks are not proof that every request was captured. Detect missing receipts, duplicate export sources, unresolved admissions, and child requests outside the governed path.

Value: companies can trust the measurement before allowing automatic action.

### 2. Better evidence for each optimization

Add matched task groups, predefined quality checks, minimum observation windows, and uncertainty estimates. Compare p95 completion time as well as averages. Track delayed regressions and maintenance costs.

Keep measured spend, estimated avoided cost, subscription quota, compute, and human effort separate. Never turn a shorter transcript into a billed-savings claim.

Value: finance and engineering can assess the same result without inflated ROI claims.

### 3. A tested catalog of narrow controls

Expand only controls that demonstrate positive payback: targeted log extraction, reusable deterministic scripts, selective instruction loading, safe reference reuse, and cache-aware context handling.

Each control needs eligibility conditions, a version, an owner, a limited pilot, a rollback path, and evidence of task equivalence. Preserve complete source artifacts and verification requirements.

Value: repeatable savings with understandable behavior, rather than an agent improvising cheaper plans.

### 4. Managed policy and budgets

Add organization/team/project budget scopes, explicit accounting periods, approved exceptions, staged policy rollout, and administrative ownership. Separate advisory optimizations from mandatory spending controls.

The current local roles and policy files assume a trusted launcher and protected OS environment. Strong enforcement needs a separately controlled runner or gateway. A plugin alone cannot stop requests made outside its integration.

Value: predictable spend and ownership across teams.

### 5. Security and procurement readiness

Add enterprise identity integration when offering a service, tenant isolation, scoped access, configurable retention, external audit export, secure updates, dependency inventory, and a documented vulnerability process.

Support deployment inside the customer's environment where required. Capture metadata by default; raw prompts and code should not be required for routine accounting.

Value: an installation security and procurement teams can approve. Do not advertise certifications before obtaining them.

### 6. Operational reliability

Add recovery procedures, admission reconciliation, ledger backup/restore, disk quotas, retention for long-lived accounting data, and load tests. Document behavior during missing telemetry, provider timeouts, unavailable storage, and policy errors.

Export health metrics through existing monitoring. Avoid a mandatory dashboard or continuously reasoning supervisor.

Value: cost controls do not become a new source of outages or operational work.

### 7. Skill lifecycle management

Connect skill selection and execution to actual usage records. Detect overlapping skills, track failures and maintenance, and propose reuse or retirement. Add approvals and rollback for shared organizational instructions.

Prefer existing tools, scripts, references, and templates before creating skills. Observed recurrence starts evaluation; it does not automatically justify a skill.

Value: reusable knowledge remains useful instead of becoming another context tax.

## Guardrails for building Token Police itself

- Set an explicit implementation and validation budget for each increment.
- Require a named customer problem, expected benefit, and acceptance check before adding a feature.
- Keep routine monitoring at zero model calls; account for process, storage, and integration overhead.
- Deduplicate findings and cap paid reviews, investigation scope, notifications, and runtime.
- Stop optional investigation when its allowance is exhausted; retain necessary deterministic controls.
- Do not build a hosted platform, dashboard, multi-agent auditor, or broad model router before a pilot demonstrates demand.
- Keep host-specific adapters small; avoid claims of universal interception or guaranteed savings.

## Recommended next decision

Choose one team, one recurring workflow, and one control. Connect real telemetry, run the bounded pilot, and retain the control only if its benefit survives complete accounting and quality checks. Use that evidence to decide which enterprise integration deserves investment next.
