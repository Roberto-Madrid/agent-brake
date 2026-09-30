"""Local hook decisions and a bounded-output command runner."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from .ledger import Invalid, canonical, digest, integer, label
from .governance import enabled, intervention

DEFAULTS = {"mode": "observe", "max_session_tool_calls": None, "read_lines": 200,
            "grep_lines": 100, "large_output_bytes": 32000, "large_input_tokens": 50000,
            "failure_alert_after": 3, "repeat_success_after": None, "session_warning_pct": 80}


def policy(path=None, org=None):
    result = dict(DEFAULTS)
    if path:
        loaded = json.loads(Path(path).read_text())
        if not isinstance(loaded, dict) or loaded.keys() - DEFAULTS.keys():
            raise Invalid("unknown policy fields")
        result.update(loaded)
    central = (org or {}).get('controls', {})
    if not isinstance(central, dict) or central.keys() - DEFAULTS.keys():
        raise Invalid('unknown organization control')
    for key, value in central.items():
        if key == 'mode':
            if value == 'enforce':
                result[key] = value
            elif value != 'observe':
                raise Invalid('invalid organization mode')
        elif value is not None:
            integer(value, key)
            result[key] = value if result[key] is None else min(value, result[key])
    if result["mode"] not in ("observe", "enforce"):
        raise Invalid("mode must be observe or enforce")
    for k, v in result.items():
        if k == "mode" or k in ("max_session_tool_calls", "repeat_success_after") and v is None:
            continue
        integer(v, k)
        if k != "max_session_tool_calls" and v == 0:
            raise Invalid(f"{k} must be positive")
    if result['session_warning_pct'] > 100:
        raise Invalid('session_warning_pct must be 1..100')
    return result


def hook(ledger, payload, config, host):
    """Never emit permission allow: cost control must not grant tool permission."""
    if not isinstance(payload, dict):
        raise Invalid('hook payload must be an object')
    event = payload.get("hook_event_name")
    if event not in ("SessionStart", "PreCompact", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
        return None
    session = label(payload.get("session_id"), "session_id")
    task = os.environ.get('TOKEN_POLICE_TASK', f'session:{session}')
    with ledger.transaction():
        ledger.db.execute('INSERT INTO hook_health VALUES (?,?,?,?,1,?) ON CONFLICT(host,session,event,synthetic) '
                          'DO UPDATE SET hits=hits+1,last_seen=excluded.last_seen',
                          (host, session, event, int(payload.get('_token_police_synthetic') is True), time.time()))
        if event in ('SessionStart', 'PreCompact'):
            ledger.db.execute('INSERT INTO context_generations VALUES (?,1) ON CONFLICT(task) '
                              'DO UPDATE SET generation=generation+1', (task,))
            # Explicit CLI task IDs need not match host session IDs.
            ledger.db.execute("INSERT INTO context_generations VALUES ('*',1) ON CONFLICT(task) "
                              'DO UPDATE SET generation=generation+1')
            return None
    call = label(payload.get("tool_use_id"), "tool_use_id")
    name = label(payload.get("tool_name"), "tool_name")
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        raise Invalid("tool_input must be an object")
    identity = digest([host, session, call])
    fingerprint = digest([name, args])
    task = os.environ.get('TOKEN_POLICE_TASK', f'session:{session}')
    if event == "PreToolUse":
        with ledger.transaction():
            prior = ledger.db.execute("SELECT fingerprint FROM tools WHERE id=?", (identity,)).fetchone()
            if prior and prior[0] != fingerprint:
                raise Invalid("tool call ID reused with different arguments")
            decision_id = digest([identity, task, config, [enabled(ledger, r, task=task) for r in ('bounded_read', 'session_call_limit')]])
            # Retrying delivery of the same hook does not consume another slot.
            old = ledger.db.execute("SELECT data FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if old:
                return json.loads(old[0])
            output = None
            n = ledger.db.execute("SELECT COUNT(*) FROM tools WHERE session=?", (session,)).fetchone()[0]
            cap = config["max_session_tool_calls"]
            if cap is not None and cap > 0 and n + 1 >= cap * config.get('session_warning_pct', 80) / 100:
                ledger.find('session_budget_warning', [host, session], {'count': n, 'limit': cap,
                            'action': 'Finish necessary verification; inspect status before additional optional dispatches.'})
            if cap is not None and n >= cap and not prior and enabled(ledger, 'session_call_limit', task=task):
                ledger.find("session_call_limit", [host, session], {"count": n, "limit": cap})
                if config["mode"] == "enforce":
                    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                              "permissionDecisionReason": f"Token Police: session limit of {cap} tool calls reached. Inspect status; the owner can set a task-scoped, expiring session_call_limit exception with an audited reason."}}
            # Only known native Claude read tools. No regex shell rewriting.
            if output is None and host == "claude" and name in ("Read", "Grep") and enabled(ledger, 'bounded_read', task=task):
                field, limit = ("limit", config["read_lines"]) if name == "Read" else ("head_limit", config["grep_lines"])
                value = args.get(field)
                if value is None or type(value) is int and (value == 0 or value > limit):
                    ledger.find("bounded_read", [session, call], {"tool": name, "limit": limit})
                    if config["mode"] == "enforce":
                        output = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "updatedInput": {**args, field: limit},
                                  "additionalContext": f"Token Police bounded {name} to {limit} lines. Results may be partial; paginate or narrow the query before concluding absence."}}
            if not output or output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny":
                ledger.db.execute("INSERT OR IGNORE INTO tools VALUES (?,?,?,?,?,?,?)",
                                  (identity, session, name, fingerprint, "pending", None, time.time()))
            ledger.db.execute("INSERT INTO decisions VALUES (?,?)", (decision_id, canonical(output)))
            if output:
                rule = 'session_call_limit' if output['hookSpecificOutput'].get('permissionDecision') == 'deny' else 'bounded_read'
                intervention(ledger, digest([identity, rule, config]), os.environ.get('TOKEN_POLICE_TASK', f'session:{session}'), rule, policy=digest(config))
        return output
    response = payload.get("tool_response")
    failed = event == "PostToolUseFailure" or isinstance(response, dict) and (response.get("isError") is True or
                    isinstance(response.get("exit_code"), int) and response["exit_code"] != 0)
    # Count bytes, never retain tool content or commands in the ledger.
    size = len(canonical(response).encode()) if response is not None else None
    with ledger.transaction():
        ledger.db.execute("INSERT OR IGNORE INTO tools VALUES (?,?,?,?,?,?,?)",
                          (identity, session, name, fingerprint, "pending", None, time.time()))
        ledger.db.execute("UPDATE tools SET status=?,output_bytes=? WHERE id=?", ("failed" if failed else "ok", size, identity))
        if size is not None and size > config["large_output_bytes"]:
            ledger.find("large_tool_output", identity, {"tool": name, "bytes": size, "action": "Use the bounded runner or native pagination."})
        if failed:
            n = ledger.db.execute("SELECT COUNT(*) FROM tools WHERE session=? AND fingerprint=? AND status='failed'",
                                  (session, fingerprint)).fetchone()[0]
            if n >= config["failure_alert_after"]:
                ledger.find("repeated_failure", [session, fingerprint], {"tool": name, "failures": n,
                            "action": "Review changed inputs before another retry; advisory only."})
        threshold = config.get("repeat_success_after")
        if not failed and threshold is not None:
            sessions = ledger.db.execute("SELECT COUNT(DISTINCT session) FROM tools WHERE fingerprint=? AND status='ok'",
                                         (fingerprint,)).fetchone()[0]
            if sessions >= threshold:
                ledger.find("repeatable_action", fingerprint, {"tool": name, "sessions": sessions,
                            "action": "Same successful arguments recurred. Use an existing script. This finding does not create a skill.",
                            "billing_savings": "unknown"})
    return None


def scan(ledger, config):
    key = digest(config)
    with ledger.transaction():
        state = ledger.db.execute("SELECT last_row FROM scan_state WHERE policy=?", (key,)).fetchone()
        last = state[0] if state else 0
        rows = ledger.db.execute("SELECT rowid,data FROM events WHERE rowid>? ORDER BY rowid LIMIT 1000", (last,)).fetchall()
        for row in rows:
            event = json.loads(row[1])
            value = event.get("input_tokens")
            if value is not None and value > config["large_input_tokens"]:
                ledger.find("large_model_input", event["event_id"], {"task_id": event["task_id"], "input_tokens": value,
                            "action": "Inspect context loading only if this task did not require the material."})
        if rows:
            last = rows[-1][0]
        ledger.db.execute("INSERT OR REPLACE INTO scan_state VALUES (?,?)", (key, last))
    return {"scanned": len(rows), "has_more": bool(ledger.db.execute("SELECT 1 FROM events WHERE rowid>? LIMIT 1", (last,)).fetchone()),
            "findings": ledger.findings()}


def run_bounded(command, directory, limit=12000, timeout=60, env=None):
    if not command:
        raise Invalid("command required after --")
    integer(limit, "limit")
    integer(timeout, "timeout")
    if not 512 <= limit <= 1024 * 1024 or not 1 <= timeout <= 86400:
        raise Invalid("output limit must be 512..1048576 bytes; timeout 1..86400 seconds")
    root = Path(directory) / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700)
    out_path, err_path = root / "stdout.log", root / "stderr.log"
    start = time.perf_counter()
    expired = False
    with out_path.open("wb") as out, err_path.open("wb") as err:
        # No shell interpretation. Executing this command remains caller-authorized.
        process = subprocess.Popen(command, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                   start_new_session=os.name == "posix", env=env)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired = True
            if os.name == "posix":
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            else:
                # taskkill /T terminates descendants; arguments are never shell-interpreted.
                killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if killed.returncode != 0 and process.poll() is None:
                    process.kill()
            process.wait()
            code = 124
    snippets = {}
    for name, path in (("stdout", out_path), ("stderr", err_path)):
        path.chmod(0o600)
        size = path.stat().st_size
        cap = limit // 2
        with path.open("rb") as stream:
            if size <= cap:
                preview = stream.read(cap)
            else:
                preview = stream.read(cap // 2)
                stream.seek(-cap // 2, 2)
                preview += b"\n[... omitted; see artifact ...]\n" + stream.read(cap // 2)
        snippets[name] = {"bytes": size, "truncated": size > cap, "path": str(path.resolve()),
                          "preview": preview.decode("utf-8", errors="replace")}
    return {"exit_code": code, "timed_out": expired, "elapsed_ms": round((time.perf_counter()-start)*1000, 3),
            "output": snippets, "billing_savings": "unknown"}
