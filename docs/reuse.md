# Cross-agent reuse contract

## Receipt v1

`activity-record FILE` accepts exactly these fields (a file or `-` for stdin):

```json
{
  "schema_version": 1,
  "event_id": "run-42:filename-check:1",
  "project_id": "demo",
  "scope_id": "client-a",
  "agent_id": "builder-1",
  "task_id": "task-42",
  "operation": "secret-names",
  "operation_version": "1",
  "input_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "status": "success",
  "evidence": "artifact:run-42:filename-check"
}
```

The example fingerprint is illustrative. Compute SHA-256 over canonical input metadata including revision, parameters, and any relevant environment version; do not hash only the operation label. Never include credentials in metadata. Fingerprints can still reveal correlations: they are not encryption or anonymization.

All strings must be nonempty and at most 256 characters. Operation is a lowercase hyphenated slug up to 64 characters. Fingerprint is 64 lowercase hex characters. Status is `success` or `failure`. IDs are caller-supplied; stable retries reuse the event ID and identical payload. Conflicting reuse of an ID fails. Distinct executions receive distinct IDs. Agents must use stable identity per logical agent, not a fresh identity for every retry.

The input contract is model-independent. Hooks do not manufacture these receipts: your runner knows the semantic operation, revision, scope, and completion evidence. It must supply them. Receipts describe completed work; do not record planned work as success. Failure receipts remain available but do not count toward success thresholds. The scanner does not independently validate evidence references or automatically link them to billed usage.

## Runner integration

1. Execute authorized work and obtain its real outcome.
2. Persist an activity receipt using `activity-record`.
3. Invoke `reuse-scan --project PROJECT --scope SCOPE` to inspect candidates.
4. Invoke `reuse-draft` with the same arguments after completion if automatic draft creation is desired.
5. Review generated files and run `reuse-state ID --state approved`; then install using the host's normal skill installation mechanism.

`--minimum N` is 3 by default, accepts 2..1000, and still requires two distinct successful agents. Counts are cumulative, not a rolling-window confidence score. Three runs of a useful required check can be repetitive without being wasteful. The output recommends procedure reuse and never advises skipping validation. Multiple projects/scopes/operation versions remain separate. For a breaking contract change, increment `operation_version`; unrecognized versions are not draftable.

## Lifecycle and persistence

SQLite transactions serialize receipt insertion, draft registry changes, and audit writes. Draft directories are installed by atomic local rename. A crash between rename and registry insert leaves a recoverable directory: a later retry verifies exact contents before registration. Repeated drafting preserves an existing package and lifecycle state. Approval verifies the complete file set, rejects symlinks and changed content, and records an audit entry. It does not execute files, grant host permissions, or install anything.

A generated package's ID is derived from project/scope/operation/version. Approval and retirement require admin under managed organization policy; activity recording and drafting require operator or admin. A viewer can scan. Without managed policy, the invoking OS user owns these actions. The local directory and database require a trusted OS user boundary; this is not protection against malicious same-user processes.

Review the recipe code in `token_police/reuse.py` before adding operations. Each recipe needs a narrow deterministic contract, documented inputs/output and failure behavior, no captured-command evaluation, and bounded output. Keep the generated skill short. Author novel scripts through the task-owning agent with the project's ordinary review process; the monitoring loop makes no model calls.

Retiring a registry entry does not disable installed copies. Changes to a recipe require a new operation version and explicit support in the catalog/version selection logic. Package files alone are not a hermetic execution environment: pin the Python package, interpreter, and relevant tools separately. No automatic retention, distributed synchronization, in-flight locking, or generated-skill billing attribution is implemented by this module.
