# v0.2 operations

Use `python scripts/tp.py --help` for commands. All normal collection and calculation are deterministic. No daemon or automatic model review is installed.

## Integrated workflows

Use `token_police.workflow.Workflow(ledger, task, project, workload, cohort, org)` around a caller-owned workflow. `call(callback, request_id, estimate_microusd, format_name, rates)` admits once, executes the supplied callback, and settles its final response. Supply a conservative estimate and the provider's own output cap. An exception leaves spend reserved; reconcile it before retrying. `outcome(accepted, evidence, rework_count, human_ms)` records external verification. Never infer acceptance from a successful process exit.

Alternatively, `collect manifest.json` imports up to 32 explicit sources, 1000 lines per source per pass. Each source has absolute `path`, `task`, `project`, `workload`, `cohort`, optional `format`, `rates`, and `actor`. Sources are append-only. Set `TOKEN_POLICE_SOURCES` to an owner-controlled manifest to collect after host tool completion. Missing sources remain visible; no filesystem search or model wake occurs.

`coverage --project PROJECT` measures registered task coverage, not uninstrumented requests. Register tasks before work starts. Use one receipt source for each charge; importing the same charge through two different formats can double count it.

The `otel` adapter accepts one final span per JSONL line, with `trace_id`, `span_id`, and a flattened `attributes` map. Standard keys: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and request/response model. Optional exporter-owned keys: `token_police.cached_input_tokens`, `token_police.cache_write_tokens`, `token_police.cost_microusd`, `token_police.cost_source`, and `token_police.aggregate`. These extensions are not OpenTelemetry standard attributes. Missing cache or cost stays null and is not priced from a rate card. A span that carries a known cost but no token counts is still imported. Spans with neither usage nor cost are skipped. Raw OTLP envelopes, `spans` batches, and `token_police.aggregate: true` raise, so the cursor does not advance past hidden charges. One flattened parent can still conceal child charges; export only the final charge span, and keep retries as separate span IDs. See `examples/otel.jsonl`.

## Managed policy and review budgets

Set `TOKEN_POLICE_ORG_POLICY` to an absolute administrator-controlled JSON file. Fields: `version`, `roles` (OS username to viewer/operator/admin), `limits`, optional `projects`, `controls`, `retention_days`. Local/project limits can only tighten central settings. POSIX group/world writable policy files are rejected. Windows ACLs must be configured by deployment tooling.

Example limits: `project_microusd`, `task_microusd`, `governor_microusd`, `reviews`, `inspections`, `notifications`, `review_runtime_ms`, `cooldown_seconds`. Money is integer micro-USD. Project and governor budgets are cumulative for that project/state, not automatically monthly. Governor allowance defaults to zero. Estimates are admissions, not a guarantee that a provider cannot exceed the estimate.

Use `task-register`, then `admit`, `admission-settle`, or `admission-release --confirmed-not-executed`. The legacy caller-selected `reserve --cap` is rejected under managed policy. All children must share task/project attribution and the governed dispatch path.

`review-run --task T --id R --issue I --estimate N --timeout 60 -- COMMAND` bounds an explicitly requested reviewer process. It exports `TOKEN_POLICE_REVIEW_ID`, `TOKEN_POLICE_TASK`, and `TOKEN_POLICE_RECEIPT_FILE`. The reviewer writes one final canonical governor receipt to that file. Missing receipts keep the reservation held and produce a non-success CLI result. Use `review-action` before an inspection or notification. These allowances require a cooperating runner; they cannot intercept arbitrary activity outside the integration.

Do not use receipt IDs containing customer content. Policy configuration and command execution are trusted inputs. OS roles are local authorization, not tenant isolation. Anyone able to change the launcher, database, or integration can bypass local controls.

## Rules and evidence

Built-in rules start with version 1 and expire after 30 days. `rule-register` accepts `id`, `version`, `owner`, Unix `expires`, `minimum`, `max_latency_increase_pct`, `max_human_increase_pct`. New versions start as candidates. `rule-state` changes state with a required reason; activating a version disables other active versions.

Register baseline and applied task assignments with `intervention`. Hook assignments use `TOKEN_POLICE_TASK` when set, otherwise session IDs that need explicit task mapping. `rule-report` requires complete registered cohorts, one changed control, cost, verified outcomes, task elapsed time, human time, and explicit coverage/comparability attestation. `rule-evaluate` additionally disables a harmful rule. It cannot undo past tool effects or edits.

`cycle manifest.json` combines collection and evaluation. Its manifest has `sources` and up to ten `evaluations`. Each evaluation contains `rule`, `version`, `workload`, `baseline`, `treatment`, and boolean `attest_complete`. Default is report only; `--apply` permits disabling harmful rules and requires admin role under managed policy. Run this from a trusted workflow completion job, not through an LLM. Incomplete evidence never enables a rule or establishes savings.

`exception --task T --rule RULE --expires UNIX --reason TEXT` creates an audited, expiring task exception. It does not increase monetary budgets. Observe-mode hook errors return success with an error diagnostic; enforcement failures block pre-tool execution. Post-tool hooks cannot undo effects.

## Narrow transformations and lifecycle

`read-reference --root ROOT --file FILE --task T` returns bounded text once, then a content hash/reference for an unchanged source in the same task. It reopens and hashes the source each time. Use `--force` after context loss. Permissions and the explicit allowed root are checked on every call. Sources are limited to 8 MiB. Changed sources invalidate reuse.

`json-select` uses an exact JSON pointer and preserves the selected value. It marks omitted context and rejects oversized selections. Neither transformation claims billed savings. `cache-report` reports known cache coverage and never rewrites prompts automatically.

`skill-record` accepts `id`, `skill`, `version`, `task`, `kind` (use/build/maintenance), nullable `cost_microusd`, nullable `saved_estimate_microusd`, boolean `success`, and `evidence`. Include selection, loading, execution, and validation in costs. `skill-report` proposes retirement based on observed use, cost, failures, or inactivity. Estimated avoided cost is not causal proof. These records are analytic annotations; also record actual charges in the usage ledger once.

`retention` previews generated artifact cleanup; `--apply` performs it. Accounting and audit records remain retained. Raw command output is not protected by a disk quota; use an OS/container quota in deployment. `audit-check` detects a broken local hash chain, but a privileged attacker can rewrite it. Export externally for stronger evidence.

## Repeated checks

These commands replace copy-paste one-liners. They do not decide lane, blockage, model escalation, or whether to wake another bot, and they do not report savings.

`gate-exit -- COMMAND` records the exit code. Full logs stay on disk. A non-zero exit is `fail`; the owner decides whether that is a small fix or a block. `diffstat --root ROOT --path-cap N` returns a capped path list and shortstat, never a patch. `secret-names --root ROOT` lists suspicious filenames and does not open them. `skill-budget --file SKILL.md` counts words against the package cap.

`repeat_success_after` is off unless a policy sets a positive session count. The hook then records one `repeatable_action` finding for the same successful arguments. It does not deny the tool and does not write a skill. A tool hook still cannot see another bot's chats or profiles. Draft a skill only through `skill-eval` when the repeat needs judgment; a deterministic repeat stays one of the commands above.
