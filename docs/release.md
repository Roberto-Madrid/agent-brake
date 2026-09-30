# Private release 0.3.0

Distribution is private by the owner's request. Do not submit either package to a public directory or change GitHub visibility.

## Release checks

Use Python 3.10+:

```sh
python -m unittest discover -s tests -v
python scripts/validate_package.py
python scripts/demo.py
python scripts/build_release.py
python scripts/verify_hosts.py --claude /path/to/claude --codex /path/to/codex
```

The last command checks native manifests and catalog discovery using command-line configuration overrides and a temporary directory. It makes no model calls, installs no plugin, and edits no host settings. Official host tools must already be available. Core CI runs on Windows, macOS and Linux; Claude validation is pinned to 2.1.285 on Linux.

The ZIPs contain one plugin at their root; catalogs stay in the repository. ZIP timestamps, ordering and file modes are fixed. Checksums cover the complete archives. Package builds never publish or upload anything. The GitHub packaging workflow uploads artifacts only to this private repository.

## Reviewer cases

| Case | Action | Expected behavior |
| --- | --- | --- |
| Fresh installation | Run setup, doctor, status | Supported interpreter pinned; missing host instrumentation is explicit |
| Known usage | Import canonical final receipts twice | Second import adds zero events; immutable totals preserved |
| Large output | Wrap an authorized command with `run` | Bounded preview, full local logs, original exit status |
| Lost context | Read a reference; compact or resume; read again | Lifecycle event invalidates reuse and returns content |
| Pilot evidence | Run `report` with complete outcomes and explicit attestation | Cost per accepted task, quality, latency and human-effort metrics; estimates labelled |
| Missing usage | Ask for savings without receipts | Insufficient evidence; no invented spend or savings |
| Scope escape | Read a reference outside the supplied root | Rejected; no content returned |
| Permission escalation | Trigger a read limit or session cap | Narrow supported Claude rewrite or deny; never permission allow |

These cases are covered by deterministic fixtures. Host runtime dispatch, trust UX, and real provider reconciliation still require a pilot. Manifest success does not prove hook coverage. The core cannot observe unrelated chats, hosted tools, or arbitrary model calls.

## Future public listing

The metadata and square vector assets are prepared, but no public submission is authorized. If the owner later requests it, recheck both providers' current rules and arrange reviewer access, publisher identity verification, required public listing contacts/policies, and live host testing. Do not invent public URLs for this private repository.

Official references checked 2026-09-30: [OpenAI packaging](https://developers.openai.com/plugins/build/plugins), [OpenAI submission errors](https://developers.openai.com/plugins/deploy/submission-errors), [OpenAI hooks](https://learn.chatgpt.com/docs/hooks), [Claude plugin manifest](https://code.claude.com/docs/en/plugins-reference), [Claude private marketplaces](https://code.claude.com/docs/en/plugin-marketplaces).
