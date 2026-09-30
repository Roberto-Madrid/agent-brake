# Security

Report vulnerabilities privately through the repository owner's configured contact or GitHub private vulnerability reporting once the repository is published. Do not attach raw logs, credentials, or private transcripts to public issues.

Treat policies, rates, and scripts as trusted operator inputs. Keep the ledger private. Do not load config from arbitrary repository content automatically. The CLI never evaluates imported code or invokes a shell around JSON fields. `run` intentionally executes an explicitly supplied command and is not a security boundary.

Cost controls never grant tool permissions. Hook errors are explicit; supported pre-tool hook errors exit 2. A missing interpreter or host-specific hook failure may behave differently: test that runtime before relying on enforcement. Post-tool controls cannot undo completed side effects. Tool hooks do not cover every paid action.
