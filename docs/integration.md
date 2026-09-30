# Integration

## Requirements and setup

Python 3.10+ and a POSIX shell are required for bundled hooks. On Windows use Git Bash, whose `sh.exe` must be available to the host. The Python core has no third-party dependencies. A supported local execution environment is necessary; a web installation does not deploy hook scripts.

Clone the private repository using your own authorized GitHub account:

```sh
gh repo clone Roberto-Madrid/token-police
cd token-police
python scripts/setup.py
```

If `python` is older than 3.10, run setup with the absolute path of a supported Python executable. The launcher checks `TOKEN_POLICE_PYTHON`, then a pinned `python-path` in the state directory, then `python3`, `python`, and `py -3`. It rejects unsupported interpreters with an actionable error. It preserves hook stdin and never shell-evaluates an interpreter path.

Set `TOKEN_POLICE_HOME` to the private state directory printed by setup in the environment inherited by your host. Run setup and CLI reports against that same directory. Otherwise the host may use `PLUGIN_DATA` or `CLAUDE_PLUGIN_DATA` instead of `~/.token-police`. `TOKEN_POLICE_PYTHON` can pin an absolute interpreter path without a setup file. Do not commit state, raw artifacts, or credentials.

## Anthropic / Claude Code

From a local checkout:

```sh
claude plugin marketplace add /absolute/path/to/token-police
claude plugin install token-police@token-police-private
```

For users with repository access, the private Git source is also supported:

```sh
claude plugin marketplace add Roberto-Madrid/token-police
claude plugin install token-police@token-police-private
```

For an isolated trial use `claude --plugin-dir /absolute/path/to/token-police`. Validate the catalog with `claude plugin validate --strict .` and the plugin with `claude plugin validate --strict .claude-plugin/plugin.json`. Run `python scripts/verify_hosts.py --claude /path/to/claude` for both checks in their separate layouts.

The Claude manifest is `.claude-plugin/plugin.json`. Hooks load from `hooks/hooks.json` and explicitly use Bash. Default observe mode records findings without modifying requests. Configured enforcement on native Read/Grep only sets the line limit, preserves other inputs, and omits permission allow. Partial results require pagination before concluding absence. Shell commands are never rewritten.

## OpenAI / Codex

The portable `plugin.json` declares the OpenAI hook file and listing metadata. `.agents/plugins/marketplace.json` provides a private catalog pointing to the plugin at the repository root.

```sh
codex plugin marketplace add /absolute/path/to/token-police
codex plugin add token-police@token-police-private
```

Alternatively add `Roberto-Madrid/token-police` as the marketplace source from an account with repository access. For supported desktop surfaces, refresh the Plugins directory after adding the local source and select Token Police Private. Installation and hook trust are separate: review and trust the current hook definition in the host before relying on monitoring. The package never grants that trust on your behalf.

The Codex adapter uses supported PreToolUse deny responses and silent successful PostToolUse handling. Hosted tools and some specialized paths do not pass through local hooks. Tool hooks do not intercept every model request or cap model thinking. Shell, MCP, edits, and asynchronous unified exec should each be checked during a live pilot.

## Verify monitoring

After installation, run a harmless host tool call, then:

```sh
python scripts/tp.py doctor
python scripts/tp.py status
```

`runtime_observed` indicates a received nonsynthetic event, not complete interception. Trust status remains `not_inspected`. Synthetic launcher checks do not count as runtime observation. Hook errors and inactive rules require investigation before enabling enforcement.

Both hosts use `sh "${CLAUDE_PLUGIN_ROOT}/scripts/launch.sh" hook --host ...`; Codex provides that root variable for compatibility. SessionStart and PreCompact reset reference reuse. Normal successful observe hooks emit no model-visible text and make no model calls.

## Controls and runner integration

Set `TOKEN_POLICE_POLICY` to an absolute, owner-controlled JSON file to select controls. Start in observe mode, then enable one narrow control after a measured pilot. Never use a shared writable untrusted state or policy directory. See [operations](operations.md) and [0.3 additions](v0.3-operations.md).

A runner must emit final canonical usage and externally verified outcomes. Reserve/admit and settle around paid model dispatch to enforce budgets. Account for Token Police reasoning as `actor:governor` and setup/maintenance as `purpose:overhead`. Collection making zero model calls does not make human review or model-driven exception analysis free.

The standalone CLI can serve other agents through canonical JSONL; no universal interception or other bots' quota access is claimed. Plain chat without local execution cannot monitor or constrain unrelated agents. No MCP server is required for this private release.

## Release scope

Version 0.3.0 passes local strict Claude manifest checks and Codex catalog recognition. Synthetic hooks, accounting, concurrency, output bounds, process-tree cleanup and packaging are tested. Live host dispatch coverage, provider billing reconciliation and real savings require actual pilot evidence. Packages are private and have not been submitted to a public directory.

Official references checked 2026-09-30: [OpenAI packaging](https://developers.openai.com/plugins/build/plugins), [OpenAI hooks](https://learn.chatgpt.com/docs/hooks), [Claude manifests](https://code.claude.com/docs/en/plugins-reference), [Claude marketplaces](https://code.claude.com/docs/en/plugin-marketplaces), [Claude hooks](https://code.claude.com/docs/en/hooks).
