"""Exact cross-agent procedure discovery and deterministic, script-backed skill drafts.

Activity is explicit instrumentation, not inference from private conversations.
Generated code comes only from the fixed recipe catalog, never event payloads.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from .ledger import Invalid, canonical, digest, label
from . import governance as gov

# Adding a recipe is a code-reviewed extension, not permission to execute a log entry.
RECIPES = {
    'secret-names': ('List suspicious filenames without opening their contents.', 'secret-names'),
    'diffstat': ('Summarize changed paths without loading patch bodies.', 'diffstat'),
    'skill-budget': ('Check the word budget of a skill document.', 'skill-budget'),
}
FIELDS = {'schema_version', 'event_id', 'project_id', 'scope_id', 'agent_id', 'task_id',
          'operation', 'operation_version', 'input_fingerprint', 'status', 'evidence'}


def initialize(ledger):
    ledger.db.executescript('''
    CREATE TABLE IF NOT EXISTS activities(id TEXT PRIMARY KEY,project TEXT,scope TEXT,
      agent TEXT,operation TEXT,version TEXT,status TEXT,data TEXT,created REAL);
    CREATE INDEX IF NOT EXISTS activity_scope ON activities(project,scope,operation,version,status);
    CREATE TABLE IF NOT EXISTS reuse_packages(id TEXT PRIMARY KEY,project TEXT,scope TEXT,
      operation TEXT,version TEXT,state TEXT,manifest TEXT,created REAL);
    ''')


def record(ledger, event):
    initialize(ledger)
    if not isinstance(event, dict) or set(event) != FIELDS or type(event['schema_version']) is not int or event['schema_version'] != 1:
        raise Invalid('activity requires exactly the documented schema_version 1 fields')
    for key in FIELDS - {'schema_version'}:
        label(event[key], key)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', event['operation']) or len(event['operation']) > 64:
        raise Invalid('operation must be a lowercase slug of at most 64 characters')
    if not re.fullmatch(r'[0-9a-f]{64}', event['input_fingerprint']):
        raise Invalid('input_fingerprint must be a SHA-256 hex digest of the input revision and parameters')
    if event['status'] not in ('success', 'failure'):
        raise Invalid('status must be success or failure')
    value = canonical(event)
    with ledger.transaction():
        old = ledger.db.execute('SELECT data FROM activities WHERE id=?', (event['event_id'],)).fetchone()
        if old:
            if old[0] != value:
                raise Invalid('activity event ID conflicts with existing receipt')
            return {'added': False}
        ledger.db.execute('INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?)',
            (event['event_id'], event['project_id'], event['scope_id'], event['agent_id'],
             event['operation'], event['operation_version'], event['status'], value, time.time()))
        gov.audit(ledger, 'activity-record', {'event_id': event['event_id']})
    return {'added': True}


def scan(ledger, project, scope, minimum=3):
    initialize(ledger)
    label(project, 'project'); label(scope, 'scope')
    if type(minimum) is not int or not 2 <= minimum <= 1000:
        raise Invalid('minimum must be 2..1000')
    rows = ledger.db.execute('''SELECT operation,version,count(*) AS successes,
        count(DISTINCT agent) AS agents FROM activities
        WHERE project=? AND scope=? AND status='success'
        GROUP BY operation,version HAVING count(*)>=? AND count(DISTINCT agent)>=2
        ORDER BY operation,version''', (project, scope, minimum)).fetchall()
    result = []
    for row in rows:
        events = [json.loads(r[0]) for r in ledger.db.execute('''SELECT data FROM activities
            WHERE project=? AND scope=? AND operation=? AND version=? AND status='success' ORDER BY id''',
            (project, scope, row['operation'], row['version']))]
        fingerprints = {}
        for e in events:
            fingerprints.setdefault(e['input_fingerprint'], set()).add(e['agent_id'])
        key = 'agentbrake-' + row['operation'][:30] + '-' + digest([project,scope,row['operation'],row['version']])[:16]
        result.append(dict(id=key,
            operation=row['operation'], operation_version=row['version'], successes=row['successes'],
            distinct_agents=row['agents'], exact_inputs_shared_across_agents=sum(len(v)>1 for v in fingerprints.values()),
            event_ids=[e['event_id'] for e in events],
            draftable=row['operation'] in RECIPES and row['version']=='1',
            recommendation='reuse_procedure_not_results', billing_savings='unknown'))
    return result


def package_files(operation, package_id):
    description, command = RECIPES[operation]
    name = package_id
    skill = f'''---
name: {name}
description: {description} Use when this exact deterministic operation is needed.
---

Run `python scripts/run.py --help` for arguments, then invoke the script with explicit authorized paths.
The AgentBrake Python package must be installed in the same interpreter environment.
Keep native host permissions and project boundaries. Inspect the JSON result; do not infer task acceptance or monetary savings.
Always rerun for current inputs. This procedure does not cache results or replace required verification.
Do not activate this draft until its scope and generated files have been reviewed.
Provenance: AgentBrake recipe {operation} version 1; package {package_id}.
'''
    script = f'''#!/usr/bin/env python3
"""Generated from the reviewed AgentBrake {operation} v1 recipe."""
import sys
from token_police.cli import main
if __name__ == '__main__':
    raise SystemExit(main([{command!r}, *sys.argv[1:]]))
'''
    return {'SKILL.md': skill, 'scripts/run.py': script}


def draft(ledger, home, project, scope, minimum=3):
    candidates = scan(ledger, project, scope, minimum)
    directory = Path(home) / 'reuse-drafts'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    for candidate in candidates:
        if not candidate['draftable']:
            results.append({**candidate, 'state':'needs_reviewed_recipe'})
            continue
        key = candidate['id']
        files = package_files(candidate['operation'], key)
        manifest = {name: hashlib.sha256(body.encode()).hexdigest() for name,body in files.items()}
        # Atomic directory rename; a crash leaves at most an unregistered draft, recoverable on retry.
        target = directory / key
        with ledger.transaction():
            old = ledger.db.execute('SELECT * FROM reuse_packages WHERE id=?', (key,)).fetchone()
            if old:
                results.append({'id':key, 'state':old['state'], 'path':str(target)})
                continue
            if target.exists():
                verify(target, manifest)
            else:
                with tempfile.TemporaryDirectory(prefix='.draft-', dir=directory) as temp:
                    stage = Path(temp)/'package'
                    stage.mkdir(mode=0o700)
                    for name,body in files.items():
                        dest = stage/name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        # Preserve the exact UTF-8 bytes hashed in the manifest on every OS.
                        dest.write_bytes(body.encode('utf-8'))
                    os.rename(stage, target)
            ledger.db.execute('INSERT INTO reuse_packages VALUES (?,?,?,?,?,?,?,?)',
                (key,project,scope,candidate['operation'],candidate['operation_version'],'draft',canonical(manifest),time.time()))
            gov.audit(ledger, 'reuse-draft', {'id':key, 'event_ids':candidate['event_ids'], 'manifest':manifest})
        results.append({'id':key, 'state':'draft', 'path':str(target)})
    return results


def verify(target, manifest):
    if target.is_symlink() or not target.is_dir():
        raise Invalid('skill package directory missing or symlinked')
    actual = set()
    for path in target.rglob('*'):
        if path.is_symlink():
            raise Invalid('skill package contains symlink')
        if path.is_file():
            actual.add(path.relative_to(target).as_posix())
    if actual != set(manifest):
        raise Invalid('skill package file set changed; review recipe source and regenerate')
    for name, expected in manifest.items():
        if hashlib.sha256((target/name).read_bytes()).hexdigest() != expected:
            raise Invalid('skill package content changed; review recipe source and regenerate')


def state(ledger, home, key, value):
    initialize(ledger)
    if value not in ('approved','retired'):
        raise Invalid('state must be approved or retired')
    with ledger.transaction():
        row = ledger.db.execute('SELECT * FROM reuse_packages WHERE id=?', (key,)).fetchone()
        if not row:
            raise Invalid('unknown skill package')
        if value == 'approved':
            verify(Path(home)/'reuse-drafts'/key, json.loads(row['manifest']))
        ledger.db.execute('UPDATE reuse_packages SET state=? WHERE id=?', (value,key))
        gov.audit(ledger, 'reuse-state', {'id':key, 'state':value})
    return {'id':key, 'state':value, 'installed':False}
