# Validation record

Local verification on 2026-09-29, Linux, Python 3.12.14.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 31 tests passed |
| `python scripts/validate_package.py` | Package invariants passed; skill 230 words |
| `python scripts/demo.py` | Synthetic benefit +125,000 microUSD; becomes -75,000 with added governor overhead; duplicate import adds zero events |
| `python scripts/benchmark.py` | 30 local hook processes: median 36.354 ms, p95 42.091 ms; zero model calls; zero model-visible output bytes |
| Skill forward test in fresh state | Commands worked; unattested synthetic data correctly yielded insufficient evidence |

Tests exercise immutable receipts, partial JSONL import, replay, concurrency, budget reservations, missing costs, cache pricing, provider fixtures, quality regression, governance overhead, silent hooks, read bounds, dispatch limits, bounded command output, and timeouts.

The benchmark includes Python startup and local SQLite access. It is one local sample, not a fleet performance guarantee. Enforcement notices and explicit reports can add model context even though their scripts make no model calls. Model-driven exception review also has a cost.

Not yet verified: official host validators, actual Claude/Codex installation and hook coverage, Windows/macOS CI runs, provider billing reconciliation, real savings, or public marketplace acceptance. The configured CI matrix has not run remotely. No GitHub repository or marketplace listing has been created.

Release decision: suitable for a bounded pilot after host smoke testing. Do not label this enterprise-ready or claim a positive return until complete real-work measurements support it. See [pilot](pilot.md).

## v0.2 local verification

62 tests passed before the OTel collection fix. Thirty observe hooks: median 42.864 ms, p95 50.438 ms, zero model calls and zero model-visible output bytes. That hook sample was not repeated for this increment.

## 2026-09-29 collection increment

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests -q` | 76 tests passed |
| `python3 scripts/validate_package.py` | Package invariants passed; skill 255 words |
| `python3 scripts/demo.py` | Synthetic benefit +125,000 microUSD; becomes -75,000 with added governor overhead; duplicate import adds zero events |
| Local `run` of the unit tests, then `coverage` and `compare` | Tests passed. Coverage 0 on the one registered task. Compare status `insufficient_evidence`; savings null |

The new tests cover OTel known-cost retention, unknown cache pricing, envelope and aggregate rejection, collector rollback and identity checks, cycle disable behavior, governor allowance release, and org controls through the launcher. No real savings or live host compatibility is established.

## 2026-09-30 plugin checks

`python3 -m unittest discover -s tests -q` passed 83 tests, including `gate-exit`, capped `diffstat`, filename-only `secret-names`, `skill-budget`, and a `repeatable_action` finding that creates no skill. Package validation passed; the skill is 245 words. These checks do not establish savings or live host coverage.

## 0.3.0 verification — 2026-09-30

- Windows local suite: 97 tests passed using the bundled supported Python runtime.
- Offline package invariants passed; skill instructions are 273 words.
- Synthetic demo passed; reports correctly withhold savings when evidence is incomplete.
- Claude Code 2.1.285: strict marketplace and plugin manifest validation passed with no warnings.
- Installed Codex CLI: private catalog recognizes token-police 0.3.0 using one-invocation configuration overrides. Host settings and hook trust were not changed.
- Synthetic shell launcher tests cover pinned interpreter discovery, paths with spaces, preserved stdin, and silent observe handling for both hosts. Synthetic records do not claim live host observation.
- New tests cover unknown cache fields, rate provenance, supplied-statement reconciliation, status/reservations, expiring exceptions, compaction/resume invalidation, complete UTF-8 long-line pagination, and Windows descendant termination.
- Distribution tests build identical ZIPs twice and run doctor from each extracted archive.

Native catalog/manifest validation does not prove live tool coverage or real savings. Remote CI results are recorded in GitHub Actions for this private repository.


## 0.4.0 local verification — 2026-10-07

- 102 unit tests passed, including new activity idempotency/conflicts, distinct-agent thresholds, scope/version/failure isolation, draft replay, tamper detection, retirement, unknown-operation handling, and interrupted-draft recovery.
- Package invariants passed with 321 skill words.
- Existing synthetic accounting demo passed; new synthetic cross-agent demo detected three successes across two agents and created a skill plus Python wrapper.
- Reproducible archive checks ran as part of the unit suite.
- Live provider calls, host installation, actual savings, and remote CI were not required or claimed for this pass.
