# Privacy

The core makes no network requests and collects no remote telemetry. Its SQLite ledger stores usage numbers, task/cohort identifiers, outcomes/evidence pointers, hashed tool arguments, byte counts, decisions, findings, and runtime duration. Import adapters parse supplied receipts but persist only normalized fields.

The `run` command executes the command the caller supplies. That command can access its normal environment, network, and credentials; Token Police is not a sandbox. Full stdout/stderr artifacts can contain secrets. They are stored locally under a private state directory and must not be committed or included in support tickets without review.

Use separate private state directories for users/projects. Storage uses `TOKEN_POLICE_HOME`, then host `PLUGIN_DATA`/`CLAUDE_PLUGIN_DATA`, then `~/.token-police`. Hook-health counters, context epochs and pricing provenance are also local metadata. Files use restrictive modes where supported; Windows ACLs remain the operator's responsibility. State retention and deletion are controlled by the operator; stop clients before archiving/removing the directory. Keep the ledger for the pilot horizon, not indefinitely by accident.

Plugin marketplaces and model hosts have their own data policies. If a user asks an agent to inspect findings, the selected summary enters that host's model context. Routine hooks do not send summaries to a model except enforced pagination notices, explicit denial, or hook error feedback.
