"""No third-party dependencies, network calls, or model SDKs."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from .adapters import normalizer
from .checks import diffstat, gate_exit, secret_names, skill_budget
from .controls import hook, policy, run_bounded, scan
from .ledger import Invalid, Ledger, canonical
from .metrics import compare, skill_payback, summarize
from . import governance as gov
from .workflow import collect, review_run
from .optimizations import read_reference, json_select, cache_report, retention
from .reporting import status, ranked_findings, reconcile, pilot_report
from . import __version__


def parser():
    p = argparse.ArgumentParser(prog="token-police")
    p.add_argument("--home", default=os.environ.get("TOKEN_POLICE_HOME") or os.environ.get('PLUGIN_DATA')
                   or os.environ.get('CLAUDE_PLUGIN_DATA') or str(Path.home()/".token-police"))
    p.add_argument("--policy", default=os.environ.get("TOKEN_POLICE_POLICY"))
    p.add_argument('--org-policy', default=os.environ.get('TOKEN_POLICE_ORG_POLICY'))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest", help="Incrementally import newline-terminated JSONL usage receipts")
    s.add_argument("file")
    s.add_argument("--format", choices=["canonical", "openai", "anthropic", "claude", "otel"], default="canonical")
    for key in ("task", "workload", "cohort", "rates"):
        s.add_argument("--"+key)
    s.add_argument("--actor", choices=["worker", "governor"], default="worker")
    s = sub.add_parser("record", help="Record one canonical usage or final-outcome JSON object")
    s.add_argument("file", help="File path, or - for stdin")
    for cmd in ("summary", "compare", "report"):
        s = sub.add_parser(cmd)
        s.add_argument("--workload", required=True)
        if cmd == "summary":
            s.add_argument("--cohort", required=True)
        else:
            s.add_argument("--baseline", default="baseline")
            s.add_argument("--treatment", default="treatment")
            s.add_argument("--minimum", type=int, default=5)
            s.add_argument("--attest-complete", action="store_true", help="Attest comparable cohorts and all execution/setup/governance costs included")
    sub.add_parser("scan")
    sub.add_parser("findings")
    s = sub.add_parser("resolve")
    s.add_argument("id")
    s = sub.add_parser("hook")
    s.add_argument("--host", choices=["claude", "codex"], required=True)
    s = sub.add_parser("run")
    s.add_argument("--max-output-bytes", type=int, default=12000)
    s.add_argument("--timeout", type=int, default=60)
    s.add_argument("command", nargs=argparse.REMAINDER)
    s = sub.add_parser("gate-exit", help="Run a command and record its exit code without judging the failure")
    s.add_argument("--max-output-bytes", type=int, default=12000)
    s.add_argument("--timeout", type=int, default=60)
    s.add_argument("command", nargs=argparse.REMAINDER)
    s = sub.add_parser("diffstat", help="Capped git path list and shortstat; no patch body")
    s.add_argument("--root", default=".")
    s.add_argument("--path-cap", type=int, default=20)
    s = sub.add_parser("secret-names", help="List suspicious filenames; never open the files")
    s.add_argument("--root", required=True)
    s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("skill-budget", help="Count words in a skill file")
    s.add_argument("--file", required=True)
    s.add_argument("--max-words", type=int, default=349)
    s = sub.add_parser("reserve", help="Atomic task-level pre-dispatch budget admission")
    s.add_argument("--id", required=True)
    s.add_argument("--task", required=True)
    s.add_argument("--estimate", type=int, required=True, help="Estimated micro-USD")
    s.add_argument("--cap", type=int, required=True, help="Task budget in micro-USD")
    s = sub.add_parser("settle")
    s.add_argument("id")
    s.add_argument("file")
    s = sub.add_parser("release", help="Release only a request known not to have executed")
    s.add_argument("id")
    s.add_argument("--confirmed-not-executed", action="store_true", required=True)
    s = sub.add_parser("skill-eval")
    s.add_argument("file")
    for cmd in ('collect', 'rule-register', 'skill-record'):
        sub.add_parser(cmd).add_argument('file')
    s = sub.add_parser('cycle')
    s.add_argument('file'); s.add_argument('--apply',action='store_true')
    s = sub.add_parser('task-register')
    for key in ('task','project','workload','cohort'):
        s.add_argument('--'+key, required=True)
    sub.add_parser('coverage').add_argument('--project', required=True)
    s = sub.add_parser('admit')
    for key in ('id','task'):
        s.add_argument('--'+key, required=True)
    s.add_argument('--estimate', type=int, required=True)
    s.add_argument('--actor', choices=['worker','governor'], default='worker')
    s.add_argument('--issue')
    s = sub.add_parser('admission-settle')
    s.add_argument('id'); s.add_argument('file')
    s = sub.add_parser('admission-release')
    s.add_argument('id'); s.add_argument('--confirmed-not-executed',action='store_true',required=True)
    s = sub.add_parser('review-action')
    for key in ('id','review','kind'):
        s.add_argument('--'+key,required=True)
    s.add_argument('--units',type=int,default=1)
    s = sub.add_parser('review-run')
    for key in ('task','id','issue'):
        s.add_argument('--'+key,required=True)
    s.add_argument('--estimate',type=int,required=True); s.add_argument('--timeout',type=int,default=60)
    s.add_argument('command',nargs=argparse.REMAINDER)
    s = sub.add_parser('exception')
    for key in ('task','rule','reason'):
        s.add_argument('--'+key,required=True)
    s.add_argument('--expires',type=int,required=True)
    s = sub.add_parser('rule-state')
    for key in ('rule','version','state','reason'):
        s.add_argument('--'+key,required=True)
    for cmd in ('rule-report','rule-evaluate'):
        s = sub.add_parser(cmd)
        for key in ('rule','version','workload'):
            s.add_argument('--'+key,required=True)
        s.add_argument('--baseline',default='baseline'); s.add_argument('--treatment',default='treatment')
        s.add_argument('--attest-complete',action='store_true')
    s = sub.add_parser('intervention')
    for key in ('id','task','rule'):
        s.add_argument('--'+key,required=True)
    s.add_argument('--version',default='1'); s.add_argument('--action',choices=['baseline','applied','reverted'],default='applied')
    s = sub.add_parser('skill-report')
    s.add_argument('--skill',required=True); s.add_argument('--version',required=True)
    for cmd in ('read-reference','json-select'):
        s = sub.add_parser(cmd)
        for key in ('root','file','task'):
            s.add_argument('--'+key,required=True)
        if cmd == 'read-reference':
            s.add_argument('--offset',type=int,default=0); s.add_argument('--lines',type=int,default=200)
            s.add_argument('--byte-offset',type=int,default=0)
            s.add_argument('--force',action='store_true')
        else:
            s.add_argument('--pointer',required=True)
    s = sub.add_parser('cache-report')
    s.add_argument('--workload',required=True); s.add_argument('--cohort',required=True)
    s = sub.add_parser('retention')
    s.add_argument('--days',type=int,default=30); s.add_argument('--apply',action='store_true')
    sub.add_parser('audit-check')
    sub.add_parser("doctor")
    s = sub.add_parser('status')
    s.add_argument('--project'); s.add_argument('--task')
    s = sub.add_parser('reconcile')
    s.add_argument('file'); s.add_argument('--workload',required=True); s.add_argument('--cohort',required=True)
    return p


def read_json(path):
    data = sys.stdin.read(2*1024*1024+1) if path == "-" else Path(path).read_text()
    if len(data.encode()) > 2*1024*1024:
        raise Invalid("JSON payload exceeds 2 MiB")
    return json.loads(data)


def main(argv=None):
    args = parser().parse_args(argv)
    started = time.perf_counter()
    ledger = None
    conf = {'mode': 'observe'}
    policy_loaded = False
    code = 0
    try:
        org = gov.organization(args.org_policy)
        conf = policy(args.policy, org)
        policy_loaded = True
        gov.authorize(org, args.cmd)
        if args.cmd == 'cycle' and args.apply:
            gov.authorize(org, 'rule-evaluate')
        home = Path(args.home).resolve()
        ledger = Ledger(home / "ledger.sqlite3")
        if args.cmd == "ingest":
            rates = read_json(args.rates) if args.rates else None
            result = ledger.ingest(args.file, normalizer(args.format, args.task, args.workload, args.cohort, args.actor, rates))
        elif args.cmd == "record":
            result = {"added": ledger.add(read_json(args.file))}
        elif args.cmd == "summary":
            result = summarize(ledger.events(args.workload, args.cohort))
        elif args.cmd in ("compare", "report"):
            if args.baseline == args.treatment:
                raise Invalid("baseline and treatment must differ")
            function = pilot_report if args.cmd == 'report' else compare
            result = function(ledger.events(args.workload, args.baseline), ledger.events(args.workload, args.treatment), args.minimum, args.attest_complete)
        elif args.cmd == 'status':
            result = status(ledger,conf,org,args.project,args.task)
        elif args.cmd == 'reconcile':
            result = reconcile(ledger.events(args.workload,args.cohort),read_json(args.file))
        elif args.cmd == "scan":
            result = scan(ledger, conf)
        elif args.cmd == "findings":
            result = ranked_findings(ledger)
        elif args.cmd == "resolve":
            changed = ledger.db.execute("UPDATE findings SET resolved=1 WHERE id=?", (args.id,)).rowcount
            if not changed:
                raise Invalid("finding not found")
            result = {"resolved": True}
        elif args.cmd == "hook":
            payload = read_json('-')
            result = hook(ledger, payload, conf, args.host)
            if payload.get('hook_event_name') in ('PostToolUse','PostToolUseFailure') and os.environ.get('TOKEN_POLICE_SOURCES'):
                collect(ledger, read_json(os.environ['TOKEN_POLICE_SOURCES']))
        elif args.cmd == "run":
            if not gov.enabled(ledger, 'bounded_output'):
                raise Invalid('bounded_output rule disabled or expired; use native runner')
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = run_bounded(command, home / "artifacts", args.max_output_bytes, args.timeout)
            code = result["exit_code"] if result["exit_code"] >= 0 else 128 - result["exit_code"]
        elif args.cmd == "gate-exit":
            if not gov.enabled(ledger, 'bounded_output'):
                raise Invalid('bounded_output rule disabled or expired; use native runner')
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = gate_exit(command, home / "artifacts", args.max_output_bytes, args.timeout)
            code = 0 if result["verdict"] == "pass" else result["exit_code"] if result["exit_code"] >= 0 else 128 - result["exit_code"]
        elif args.cmd == "diffstat":
            result = diffstat(args.root, args.path_cap)
            code = 3 if result["verdict"] == "over_cap" else 2 if result["verdict"] == "unknown" else 0
        elif args.cmd == "secret-names":
            result = secret_names(args.root, args.limit)
            code = 3 if result["names"] else 0
        elif args.cmd == "skill-budget":
            result = skill_budget(args.file, args.max_words)
            code = 3 if result["over"] else 0
        elif args.cmd == "reserve":
            result = ledger.reserve(args.id, args.task, args.estimate, args.cap)
            code = 0 if result["dispatch"] else 3
        elif args.cmd == "settle":
            result = ledger.settle(args.id, read_json(args.file))
        elif args.cmd == "release":
            result = ledger.release(args.id)
        elif args.cmd == "skill-eval":
            result = skill_payback(read_json(args.file))
        elif args.cmd == 'collect':
            result = collect(ledger, read_json(args.file))
        elif args.cmd == 'cycle':
            from .workflow import cycle
            result = cycle(ledger,read_json(args.file),args.apply)
        elif args.cmd == 'task-register':
            result = gov.register_task(ledger,args.task,args.project,args.workload,args.cohort)
        elif args.cmd == 'coverage':
            result = gov.coverage(ledger,args.project)
        elif args.cmd == 'admit':
            result = gov.admit(ledger,args.id,args.task,args.estimate,args.actor,org,args.issue)
            code = 0 if result['dispatch'] else 3
        elif args.cmd == 'admission-settle':
            result = gov.settle(ledger,args.id,read_json(args.file))
        elif args.cmd == 'admission-release':
            result = gov.release(ledger,args.id)
        elif args.cmd == 'review-action':
            result = gov.review_action(ledger,args.id,args.review,args.kind,args.units,org)
            code = 0 if result['proceed'] else 3
        elif args.cmd == 'review-run':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            result = review_run(ledger,command,args.task,args.id,args.issue,args.estimate,org,args.timeout)
            code = result['run']['exit_code'] if result['dispatched'] else 3
            if result['dispatched'] and not result['settled'] and code == 0:
                code = 2
        elif args.cmd == 'exception':
            result = gov.exception(ledger,args.task,args.rule,args.expires,args.reason)
        elif args.cmd == 'rule-register':
            result = gov.register_rule(ledger,read_json(args.file))
        elif args.cmd == 'rule-state':
            result = gov.rule_state(ledger,args.rule,args.version,args.state,args.reason)
        elif args.cmd in ('rule-report','rule-evaluate'):
            result = gov.rule_report(ledger,args.rule,args.version,args.workload,args.baseline,args.treatment,args.attest_complete,args.cmd=='rule-evaluate')
        elif args.cmd == 'intervention':
            with ledger.transaction():
                result = gov.intervention(ledger,args.id,args.task,args.rule,args.version,(org or {}).get('version','local'),args.action)
        elif args.cmd == 'skill-record':
            result = gov.skill_run(ledger,read_json(args.file))
        elif args.cmd == 'skill-report':
            result = gov.skill_report(ledger,args.skill,args.version)
        elif args.cmd == 'read-reference':
            result = read_reference(ledger,args.root,args.file,args.task,args.offset,args.lines,args.force,args.byte_offset)
        elif args.cmd == 'json-select':
            result = json_select(ledger,args.root,args.file,args.pointer,args.task)
        elif args.cmd == 'cache-report':
            result = cache_report(ledger.events(args.workload,args.cohort))
        elif args.cmd == 'retention':
            result = retention(ledger,min(args.days,(org or {}).get('retention_days',args.days)),args.apply)
        elif args.cmd == 'audit-check':
            result = gov.audit_check(ledger)
        else:
            result = {"version": __version__, "python": sys.version.split()[0], "python_executable": sys.executable, "mode": conf["mode"],
                      "ledger": str(ledger.path), "llm_calls": 0, "network_calls": 0,
                      "host_hooks_verified": False, "money_known": "only when supplied or locally priced",
                      "next_action": 'Review hook trust in the host; run a harmless tool call and inspect status.'}
        if result is not None:
            print(canonical(result))
    except (Invalid, ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        # Never include the input record or raw tool output in diagnostics.
        if args.cmd == "hook":
            print("Token Police hook error; inspect local configuration and ledger. Control did not complete.", file=sys.stderr)
            # Pre-tool exit 2 blocks; on post-tool this is feedback, not undo.
            code = 2 if conf['mode'] == 'enforce' or args.org_policy and not policy_loaded else 0
        else:
            print(canonical({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
            code = 2
    finally:
        if ledger:
            try:
                ledger.db.execute("INSERT INTO runtime(operation,elapsed_ms,created) VALUES (?,?,?)", (args.cmd, (time.perf_counter()-started)*1000,time.time()))
            except sqlite3.Error:
                print("Token Police runtime accounting failed.", file=sys.stderr)
                code = 0 if args.cmd == 'hook' and conf['mode'] == 'observe' else 2
            finally:
                ledger.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
