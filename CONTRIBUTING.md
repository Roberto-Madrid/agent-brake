# Contributing

Keep changes scoped to deterministic accounting, bounded controls, or adapters. Add representative regression tests for changes to cost units, cache handling, event identity, concurrency, quality gates, or hook permissions. No model SDK or network dependency belongs in routine measurement. Label provider formats and limitations explicitly.

Run `python -m unittest discover -s tests -v`, `python scripts/validate_package.py`, and `python scripts/demo.py`. Do not commit local ledgers, raw transcripts, logs, credentials, or generated build files. Each automatic control must identify its exact operation, failure behavior, and rollback. Larger changes require an observed use case and a cost rationale.
