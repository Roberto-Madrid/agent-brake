# Accounting contract

## Canonical JSONL

Use one newline-terminated JSON object per event. Files may grow; each ingestion commits events and its byte cursor atomically. Incomplete trailing lines wait until the next call. A renamed/rotated or truncated source restarts ingestion; immutable event IDs deduplicate previously seen receipts. Do not edit already ingested lines. Use a new file for corrected exports. A changed payload with an existing ID fails rather than double-counting or silently replacing evidence.

All events: `schema_version:1`, globally unique `event_id`, `task_id`, `workload`, `cohort`, `kind`. Task IDs must not cross cohorts/workloads. No raw prompts, tool arguments, or secrets belong in these records.

Usage (`kind:usage`):

- `actor`: `worker` or `governor`; `purpose`: `execution` or governor-only `overhead`.
- `input_tokens`: **inclusive** of cached and cache-write tokens; `output_tokens`: inclusive of reasoning where the provider reports it that way. Never add a reasoning subtotal twice.
- `cached_input_tokens`, `cache_write_tokens`: subsets of input. Null means unknown.
- `cost_microusd`: nonnegative integer; 1 USD = 1,000,000 micro-USD. Include a charge only once. `cost_source`: `billed` or `estimated`; both cost fields are null when unknown.
- `elapsed_ms`: optional per-operation wall time. Its sum is operation time, not concurrent task makespan. `model`: optional exact label.

Outcome (`kind:outcome`): `status` is `accepted` or `failed`, `evidence` is a bounded source ID/path, `rework_count` is a nonnegative integer. One immutable final outcome per task. The owner or existing verification emits it; Token Police never grades the task by itself. A rerun after final closure is a new task ID. Multiple attempts before closure share one task ID and separate usage event IDs.

Examples: `examples/usage.jsonl`. Child agent bills use the parent task ID and unique bill IDs; do not also ingest a parent cumulative total that includes those bills. Include tool, compute, build, validation, and repair charges as separate usage events only if they are not already part of another receipt. Never invent a zero for an unavailable amount.

## Providers

`ingest --format openai|anthropic|claude --task T --workload W --cohort C file.jsonl` converts final message/response receipts. `claude` accepts exported assistant-message records, skipping other record types. These adapters are fixture-tested, not a promise that every host transcript format is stable. Export final usage once per message. Conflicting partial/streaming snapshots fail explicitly; raw SSE and cumulative session totals are unsupported.

Anthropic input/cache components become inclusive canonical input. OpenAI Chat Completions and Responses inclusive totals stay inclusive. Reasoning detail is not re-added. Host subscription percentages are not converted into API dollars.

Costs remain null unless supplied canonically or calculated using an explicit `--rates rates.json` map. The map is `{ "exact-model-name": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 2.5} }` in USD per million tokens. These numbers are **illustrative**, not current provider prices. Missing applicable rates, or any missing OTel token component, keep cost unknown. OpenAI and Anthropic adapters still treat an omitted cache-component field as zero so a rate card can price a normal usage object; a partial export that drops a nonzero Anthropic cache field can understate input. Single-rate pricing does not support automatic long-context, regional, batch, or tool-charge adjustments; use explicit canonical bills for those. No web lookup happens during measurement.

## Comparisons

For each workload/cohort, sum all usage including failed work and governance; divide by accepted task count. Treatment setup overhead contributes to the total but is not an accepted product task. Overhead is already included, so never subtract it twice.

`estimated net benefit = baseline total / baseline accepted × treatment accepted − treatment total`.

A result requires a positive configured sample minimum (default five accepted tasks each), final outcomes for execution usage, usage for outcomes, complete monetary fields, and the operator's `--attest-complete`. This threshold is a pilot convenience, not statistical significance. Lower acceptance rate or higher rework per task blocks a positive verdict. Cost sources, sizes, coverage, and quality are visible. Human time and task makespan need a separate pilot record; a positive verdict is not proof of equivalent quality or causality.

Record all Token Police model calls, including this project's setup/maintenance if allocated to the trial. Local `runtime` rows record script duration, not monetary cost. If meaningful setup, compute, model, or human overhead is unaccounted for, do not attest completeness. A coarse weekly percentage can support an observation but cannot establish the net-benefit calculation.

## Reservations

Use `reserve --id REQUEST --task TASK --estimate MICROUSD --cap MICROUSD` before your runner dispatches a paid call. Exit 0 plus `dispatch:true` grants one admission. Exit 3 means HOLD or replay; a replay is not permission to dispatch again. The runner must propagate the same parent task ID and stable request ID to all children.

After completion, `settle REQUEST receipt.json` atomically records actual usage and clears that reservation. Unknown actual cost blocks later monetary admissions. A paid call can exceed its estimate; the settlement reports that fact and the next admission accounts for it. Set the provider output cap too. No exact bill ceiling is promised.

Release only a request known not to have run: `release REQUEST --confirmed-not-executed`. A crash or timeout does not prove nonexecution. Unresolved reservations stay held for operator reconciliation, with no expiry that could accidentally admit duplicate spend. Budget values supplied by a caller are trusted configuration, not a hostile-client security boundary.
