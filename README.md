# Token Police

Deterministic usage accounting and cost controls for agent workflows, with a small skill for reviewing exceptions. **Routine collection, comparison, and hooks make zero LLM calls.** Python 3.10+, standard library only.

Status: **v0.3.0 private pilot**. OpenAI/Codex and Anthropic/Claude Code plugin packages, private marketplace catalogs, and CI. Claude strict manifest validation and Codex catalog recognition pass locally. Live host tool coverage and real-work savings remain unverified. No public directory submission or listing.

## Start here

1. Use Python 3.10+ to run `python scripts/setup.py`. The setup checks and pins that interpreter in private state; it does not edit host settings or trust hooks. If `python` is too old, use the absolute path of a supported interpreter.
2. Install from the private marketplace using [the host-specific guide](docs/integration.md). Hook launchers require `sh`; on Windows, use Git Bash.
3. Review and trust the hook definitions in your host, make a harmless tool call, then run `python scripts/tp.py status`. The report distinguishes missing instrumentation, unknown costs, and unresolved findings.
4. Import real receipts and record verified task outcomes. Run `report` for pilot cost, quality, latency, and human effort. Monitoring itself makes zero model calls.

Set `TOKEN_POLICE_HOME` to the same private directory for setup, hook execution, and CLI reports. Alternatively set `TOKEN_POLICE_PYTHON` to the absolute interpreter path. Setup's printed paths must be set in the host environment when the host uses a separate plugin data directory. Default mode is `observe`.

Private repository: `Roberto-Madrid/token-police`. Use `python scripts/build_release.py` to create OpenAI and Anthropic ZIPs plus `SHA256SUMS` under `dist/`. Only authorized repository users can access private GitHub releases and CI artifacts.

## What runs

| Component | Job | Model required |
| --- | --- | --- |
| `ingest` / `record` | Incremental receipts, immutable IDs, final task outcomes | No |
| `status` / `findings` | Monitoring health, known/unknown spend, remaining managed budgets, ranked evidence | No |
| `summary` / `compare` / `report` / `reconcile` | Accepted-task cost, rework, pilot latency/human effort, supplied billing reconciliation | No |
| Hook scripts | Detect large reads/outputs, repeat failures, and configured successful repeats; optionally cap reads and dispatches | No |
| `gate-exit` / `diffstat` / `secret-names` / `skill-budget` | Exit code, capped path list, secret filenames, skill word count | No |
| `run` | Keep complete logs on disk; return bounded stdout/stderr previews and original exit status | No |
| `reserve` / `settle` | Atomic pre-dispatch budget checks for an integrated runner | No |
| `skill-eval` | Calculate proposed reuse payback; never auto-create a skill | No |
| `token-police` skill | Review one exception or implement a reusable improvement | Yes, on request |

The task agent owns strategy and architecture. Token Police does not choose a universally “best” plan or silently downgrade models.

## Try the core

```bash
python scripts/tp.py doctor
python scripts/demo.py
python -m unittest discover -s tests -v
python scripts/validate_package.py
```

The demo uses **synthetic** data in an isolated temporary ledger. It demonstrates accounting, not real savings. No API keys, paid calls, network, or package installation are needed.

```bash
python scripts/tp.py --home /path/to/pilot-state ingest /path/to/usage.jsonl
python scripts/tp.py --home /path/to/pilot-state summary --workload log-review --cohort treatment
python scripts/tp.py --home /path/to/pilot-state compare --workload log-review
python scripts/tp.py run --max-output-bytes 12000 --timeout 60 -- python -m unittest discover -s tests
```

Without complete usage and verified outcomes, comparisons return `insufficient_evidence`. `--attest-complete` is an operator assertion that cohorts are comparable and all relevant execution/setup/governance costs are present; it is never inferred automatically. All positive before/after conclusions remain estimates.

## Install as a plugin

See [integration](docs/integration.md) for Claude Code and ChatGPT Work/Codex packaging, local marketplace commands, and limits. Keep the default `observe` mode for the initial pilot. Selectively enable `enforce` after reviewing `examples/policy.enforce.json`.

The bundle does **not** automatically access every host's token meter. Import available usage exports or have your runner emit canonical receipts. Tool hooks collect tool metadata; they do not invent model usage from tool counts. Grok Bot or another host without an interception point can use the CLI and skill in advisory mode.

## Net benefit is the release criterion

1. Choose one recurring workflow and a bounded baseline/treatment sample.
2. Export real usage and record owner-verified outcomes, including failures and rework.
3. Enable one control. Include setup and Token Police reasoning costs in the treatment cohort.
4. Compare cost per accepted task, quality, elapsed time, and manual intervention.
5. Retain the control only when benefit exceeds overhead without quality loss.

No blanket savings promise. CPU/disk/process overhead is real even when model usage is zero. Hook runtime is recorded locally; external compute and human costs must be accounted for separately or explicitly monetized in overhead events. See [accounting](docs/accounting.md).

## Repository

`token_police/` core; `scripts/` entry points and checks; `hooks/` host adapters; `skills/` short agent instructions; `tests/` failure/accounting/concurrency tests; `examples/` synthetic fixtures and policy; `docs/` integration, accounting, privacy, pilot, and release scope.

No telemetry leaves the core. Raw command artifacts remain on your machine and may contain sensitive output. See [SECURITY.md](SECURITY.md) and [privacy](docs/privacy.md).

## v0.2 additions

Managed admissions and governor allowances; automatic receipt collection for integrated runners; versioned rules and deterministic evaluation; safe reference reuse and JSON selection; skill lifecycle records; local roles, audit checking, and retention. Flattened OTel spans keep a known cost when token counts are absent and reject raw envelopes instead of marking them ingested. See [operations](docs/operations.md) and [enterprise roadmap](docs/enterprise-roadmap.md). Live host validation and real ROI remain pending. A local test-suite run can be wrapped with `run`, but without a provider export its comparison stays `insufficient_evidence`.
