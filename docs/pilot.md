# Pilot and release gates

Owner: select one team/workflow. Capture baseline normally; label workload, cohort, and task IDs before collection. Start in observe mode. Measure one control at a time without staging unnecessary duplicate paid runs.

Acceptance: lower cost per accepted task after all overhead, no meaningful quality loss, acceptable task latency, and no increase in manual supervision. Record manual time alongside the export. A small sample establishes direction, not universal savings. Disable a harmful substitution; keep useful deterministic measurement.

If real telemetry is missing, proceed only with observed waste patterns. Do not manufacture a net-positive claim. No automatic model review is launched by the implementation; optional human-invoked reviews must fit an explicit pilot budget.

Before marketplace submission:

- Run the official Claude validator and a compatible OpenAI runtime installation test.
- Verify native permission behavior, observe silence, pagination, call caps, malformed input, and coverage on each claimed platform.
- Test at least one real export per provider/version and record missing fields.
- Complete a live pilot and publish its scope, sample, overhead, quality, and limitations.
- Add the actual repository URL, publisher contact, public privacy/support URLs, and submission assets. No placeholder URLs are shipped as if registered.
- Review the license, release version, dependency policy, and CI results. Pin distribution to a release commit; do not distribute mutable personal state.

Local managed policies and review budgets are implemented in v0.2. Hostile-client tamper resistance, continuous hosted telemetry, and tenant-isolated services remain outside this local pilot. See enterprise-roadmap.md for release gates.

## Runnable local setup

This checkout can exercise one real local workflow: the unit-test run. It uses no model and records no provider bill. `run` keeps the full logs and reports `billing_savings: "unknown"`. Register the task before starting. Read `coverage` and `compare` JSON; a successful process exit is not a savings result.

```bash
python3 scripts/tp.py --home /path/to/pilot-state doctor
python3 scripts/tp.py --home /path/to/pilot-state task-register \
  --task local-tests --project token-police --workload repo-validation --cohort baseline
python3 scripts/tp.py --home /path/to/pilot-state run --max-output-bytes 12000 --timeout 120 -- \
  python3 -m unittest discover -s tests -q
python3 scripts/tp.py --home /path/to/pilot-state coverage --project token-police
python3 scripts/tp.py --home /path/to/pilot-state compare --workload repo-validation --attest-complete
```

Use `python` instead of `python3` where that is the installed interpreter. On 2026-09-29 this sequence registered one task, the tests passed, coverage was 0, and compare returned `insufficient_evidence` with null savings. Do not pass `--attest-complete` for a real cohort unless the operator has checked that the cohorts are comparable and that execution, setup, and governance costs are all present.

A flattened OTel export can be imported with `collect` or `ingest --format otel` once it is on disk. `examples/otel.jsonl` is a fixture, not a provider bill. Point `TOKEN_POLICE_SOURCES` at an absolute manifest only after the export path is owner-controlled.

## Missing access for a paid pilot

These are absent in this environment, so no baseline/treatment on live traffic was run:

- Claude Code CLI (`claude`), required for `claude plugin validate` and a local plugin install
- A Codex or ChatGPT Work CLI that can load `plugin.json` and run `hooks/codex.json`
- A provider usage export, or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, required to reconcile bills
- Authorization to spend on live API calls

Until those exist, keep the pilot in observe mode and leave monetary savings unknown.
