"""Local managed policy, atomic admissions, rule lifecycle, and audit records."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from .ledger import Invalid, canonical, digest, integer, label, validate

BUILTINS = ('bounded_read', 'session_call_limit', 'bounded_output', 'read_reference', 'json_select')
DEFAULT_LIMITS = dict(project_microusd=None, task_microusd=None, governor_microusd=0,
                      reviews=0, inspections=2, notifications=1, review_runtime_ms=60000,
                      cooldown_seconds=3600)


def principal_name():
    if os.name == 'posix':
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    return os.getlogin()


def initialize(ledger):
    ledger.db.executescript('''
    CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project TEXT,workload TEXT,cohort TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS event_times(id TEXT PRIMARY KEY,created REAL);
    CREATE TABLE IF NOT EXISTS admissions(id TEXT PRIMARY KEY,task TEXT,project TEXT,actor TEXT,
      estimate INTEGER,status TEXT,event_id TEXT,issue TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS review_actions(id TEXT PRIMARY KEY,review TEXT,kind TEXT,units INTEGER,created REAL);
    CREATE TABLE IF NOT EXISTS rules(id TEXT,version TEXT,spec TEXT,state TEXT,created REAL,PRIMARY KEY(id,version));
    CREATE TABLE IF NOT EXISTS interventions(id TEXT PRIMARY KEY,task TEXT,rule TEXT,version TEXT,policy TEXT,action TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created REAL,principal TEXT,action TEXT,data TEXT,previous TEXT,hash TEXT);
    CREATE TABLE IF NOT EXISTS skill_runs(id TEXT PRIMARY KEY,skill TEXT,version TEXT,task TEXT,data TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS read_cache(id TEXT PRIMARY KEY,fingerprint TEXT,artifact TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS context_generations(task TEXT PRIMARY KEY,generation INTEGER);
    CREATE TABLE IF NOT EXISTS hook_health(host TEXT,session TEXT,event TEXT,synthetic INTEGER,hits INTEGER,last_seen REAL,
      PRIMARY KEY(host,session,event,synthetic));
    CREATE TABLE IF NOT EXISTS exceptions(task TEXT,rule TEXT,expires INTEGER,reason TEXT,PRIMARY KEY(task,rule));
    CREATE TABLE IF NOT EXISTS usage_index(id TEXT PRIMARY KEY,project TEXT,task TEXT,actor TEXT,cost INTEGER);
    CREATE INDEX IF NOT EXISTS usage_project ON usage_index(project,task,actor);
    CREATE INDEX IF NOT EXISTS admission_project ON admissions(project,status,actor);
    CREATE INDEX IF NOT EXISTS tasks_project ON tasks(project);
    ''')
    for rule in BUILTINS:
        spec = dict(id=rule, version='1', owner='local-policy-owner', expires=int(time.time())+30*86400,
                    minimum=5, max_latency_increase_pct=10, max_human_increase_pct=0)
        ledger.db.execute("INSERT OR IGNORE INTO rules VALUES (?,?,?,'active',?)", (rule, '1', canonical(spec), time.time()))
    columns = [r[1] for r in ledger.db.execute('PRAGMA table_info(runtime)')]
    if 'created' not in columns:
        try:
            ledger.db.execute('ALTER TABLE runtime ADD COLUMN created REAL')
        except Exception:
            if 'created' not in [r[1] for r in ledger.db.execute('PRAGMA table_info(runtime)')]:
                raise
        ledger.db.execute('UPDATE runtime SET created=? WHERE created IS NULL', (time.time(),))


def audit(ledger, action, data):
    old = ledger.db.execute('SELECT hash FROM audit ORDER BY id DESC LIMIT 1').fetchone()
    previous = old[0] if old else ''
    now = time.time()
    principal = principal_name()
    value = canonical(data)
    fingerprint = digest([now, principal, action, value, previous])
    ledger.db.execute('INSERT INTO audit(created,principal,action,data,previous,hash) VALUES (?,?,?,?,?,?)',
                      (now, principal, action, value, previous, fingerprint))


def audit_check(ledger):
    previous = ''
    count = 0
    for r in ledger.db.execute('SELECT * FROM audit ORDER BY id'):
        if r['previous'] != previous or r['hash'] != digest([r['created'], r['principal'], r['action'], r['data'], previous]):
            return dict(valid=False, checked=count)
        previous = r['hash']
        count += 1
    return dict(valid=True, checked=count, head=previous, tamper_proof=False)


def organization(path=None):
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        raise Invalid('organization policy path must be absolute')
    if os.name == 'posix' and p.stat().st_mode & 0o022:
        raise Invalid('organization policy must not be group/world writable')
    raw = json.loads(p.read_text())
    if not isinstance(raw, dict) or set(raw) - {'version', 'roles', 'limits', 'projects', 'controls', 'retention_days'}:
        raise Invalid('invalid organization policy')
    label(raw.get('version'), 'policy version')
    if not isinstance(raw.get('roles'), dict) or not raw['roles']:
        raise Invalid('organization roles required')
    for principal, role in raw['roles'].items():
        label(principal, 'principal')
        if role not in ('viewer', 'operator', 'admin'):
            raise Invalid('invalid organization role')
    for config in [raw.get('limits', {}), *raw.get('projects', {}).values()]:
        validate_limits(config)
    integer(raw.get('retention_days', 30), 'retention_days')
    return raw


def validate_limits(config):
    if not isinstance(config, dict) or config.keys() - DEFAULT_LIMITS.keys():
        raise Invalid('unknown budget limit')
    for key, value in config.items():
        integer(value, key, nullable=key in ('project_microusd', 'task_microusd'))


def limits(org, project):
    result = {**DEFAULT_LIMITS, **(org or {}).get('limits', {})}
    for k, value in (org or {}).get('projects', {}).get(project, {}).items():
        old = result[k]
        # Project overrides only tighten organization limits.
        result[k] = old if value is None else value if old is None else min(old, value)
    return result


def authorize(org, command):
    if org is None:
        return
    role = org['roles'].get(principal_name())
    reads = {'doctor', 'status', 'report', 'reconcile', 'summary', 'compare', 'findings', 'coverage', 'rule-report', 'skill-report', 'audit-check', 'cache-report'}
    admin = {'rule-register', 'rule-state', 'rule-evaluate', 'exception', 'retention'}
    if role is None or role == 'viewer' and command not in reads or command in admin and role != 'admin':
        raise Invalid('operation denied by organization role')
    if command == 'reserve':
        raise Invalid('managed policy requires admit; caller-supplied budget caps are disabled')


def register_task(ledger, task, project, workload, cohort):
    for name, value in [('task', task), ('project', project), ('workload', workload), ('cohort', cohort)]:
        label(value, name)
    with ledger.transaction():
        old = ledger.db.execute('SELECT project,workload,cohort FROM tasks WHERE id=?', (task,)).fetchone()
        if old and tuple(old) != (project, workload, cohort):
            raise Invalid('task registration conflict')
        prior = ledger.db.execute('SELECT data FROM events WHERE task_id=? LIMIT 1', (task,)).fetchone()
        if prior:
            e = json.loads(prior[0])
            if (e.get('project_id'), e['workload'], e['cohort']) != (project, workload, cohort):
                raise Invalid('existing usage disagrees with registration')
        if not old:
            ledger.db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (task, project, workload, cohort, time.time()))
            audit(ledger, 'task.register', dict(task=task, project=project))
    return dict(registered=True, task=task)


def coverage(ledger, project):
    tasks = [r[0] for r in ledger.db.execute('SELECT id FROM tasks WHERE project=?', (project,))]
    with_usage = with_outcome = known_cost = 0
    for task in tasks:
        events = [json.loads(r[0]) for r in ledger.db.execute('SELECT data FROM events WHERE task_id=?', (task,))]
        usage = [e for e in events if e['kind'] == 'usage']
        with_usage += bool(usage)
        known_cost += bool(usage) and all(e['cost_microusd'] is not None for e in usage)
        with_outcome += any(e['kind'] == 'outcome' for e in events)
    n = len(tasks)
    return dict(registered_tasks=n, tasks_with_usage=with_usage, tasks_with_outcome=with_outcome,
                tasks_with_known_cost=known_cost, usage_coverage=with_usage/n if n else None,
                scope='registered tasks only; does not prove all requests were instrumented')


def admit(ledger, identity, task, estimate, actor, org=None, issue=None):
    label(identity, 'admission ID'); integer(estimate, 'estimate')
    if estimate < 1:
        raise Invalid('paid dispatch requires a positive conservative estimate')
    if actor not in ('worker', 'governor'):
        raise Invalid('invalid actor')
    if actor == 'governor':
        label(issue, 'governor issue')
    with ledger.transaction():
        t = ledger.db.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
        if not t:
            raise Invalid('register task before dispatch')
        old = ledger.db.execute('SELECT * FROM admissions WHERE id=?', (identity,)).fetchone()
        if old:
            if (old['task'], old['estimate'], old['actor'], old['issue']) != (task, estimate, actor, issue):
                raise Invalid('admission ID conflict')
            return dict(dispatch=False, reason='replay', status=old['status'])
        conf = limits(org, t['project'])
        active = list(ledger.db.execute("SELECT * FROM admissions WHERE project=? AND status='active'", (t['project'],)))
        for scope, cap in [('project', conf['project_microusd']), ('task', conf['task_microusd']),
                           ('governor', conf['governor_microusd'] if actor == 'governor' else None)]:
            if cap is None:
                continue
            where, params = 'project=?', [t['project']]
            if scope == 'task':
                where += ' AND task=?'; params.append(task)
            elif scope == 'governor':
                where += ' AND actor=?'; params.append('governor')
            spent, unknown = ledger.db.execute('SELECT COALESCE(SUM(cost),0),COUNT(*)-COUNT(cost) FROM usage_index WHERE '+where, params).fetchone()
            rs = [r for r in active if scope == 'project' or scope == 'task' and r['task'] == task or scope == 'governor' and r['actor'] == 'governor']
            if unknown:
                return dict(dispatch=False, reason=f'{scope}_cost_unknown')
            if spent + sum(r['estimate'] for r in rs) + estimate > cap:
                return dict(dispatch=False, reason=f'{scope}_budget')
        if actor == 'governor':
            reviews = list(ledger.db.execute("SELECT * FROM admissions WHERE project=? AND actor='governor' AND status!='released'", (t['project'],)))
            if len(reviews) >= conf['reviews']:
                return dict(dispatch=False, reason='review_limit')
            if any(r['issue'] == issue and (r['status'] == 'active' or r['created'] > time.time()-conf['cooldown_seconds']) for r in reviews):
                return dict(dispatch=False, reason='issue_cooldown')
        ledger.db.execute("INSERT INTO admissions VALUES (?,?,?,?,?,'active',NULL,?,?)", (identity, task, t['project'], actor, estimate, issue, time.time()))
        audit(ledger, 'dispatch.admit', dict(id=identity, task=task, actor=actor, estimate=estimate))
        return dict(dispatch=True, id=identity, limits=conf)


def settle(ledger, identity, raw):
    e = validate(raw)
    with ledger.transaction():
        r = ledger.db.execute('SELECT * FROM admissions WHERE id=?', (identity,)).fetchone()
        if not r or r['status'] == 'released' or e['kind'] != 'usage' or (e['task_id'], e.get('project_id'), e['actor']) != (r['task'], r['project'], r['actor']):
            raise Invalid('settlement does not match admission')
        if r['status'] == 'settled' and r['event_id'] != e['event_id']:
            raise Invalid('admission already settled')
        if ledger.db.execute('SELECT 1 FROM admissions WHERE event_id=? AND id!=?', (e['event_id'], identity)).fetchone():
            raise Invalid('receipt already settles another admission')
        ledger._add(e)
        ledger.db.execute("UPDATE admissions SET status='settled',event_id=? WHERE id=?", (e['event_id'], identity))
        if r['status'] != 'settled':
            audit(ledger, 'dispatch.settle', dict(id=identity, event=e['event_id']))
    return dict(settled=True, over_estimate=e['cost_microusd'] is not None and e['cost_microusd'] > r['estimate'])


def release(ledger, identity):
    with ledger.transaction():
        r = ledger.db.execute('SELECT status FROM admissions WHERE id=?', (identity,)).fetchone()
        if not r or r[0] == 'settled':
            raise Invalid('missing or settled admission')
        ledger.db.execute("UPDATE admissions SET status='released' WHERE id=?", (identity,))
        audit(ledger, 'dispatch.release_confirmed_not_executed', dict(id=identity))
    return dict(released=True)


def review_action(ledger, identity, review, kind, units, org=None):
    label(identity, 'action ID'); integer(units, 'units')
    if kind not in ('inspection', 'notification', 'runtime_ms') or units < 1:
        raise Invalid('invalid review action')
    with ledger.transaction():
        old = ledger.db.execute('SELECT review,kind,units FROM review_actions WHERE id=?', (identity,)).fetchone()
        if old:
            if tuple(old) != (review, kind, units):
                raise Invalid('review action conflict')
            return dict(proceed=False, reason='replay')
        r = ledger.db.execute("SELECT * FROM admissions WHERE id=? AND actor='governor' AND status='active'", (review,)).fetchone()
        if not r:
            return dict(proceed=False, reason='no_active_review')
        conf = limits(org, r['project'])
        key = {'inspection':'inspections', 'notification':'notifications', 'runtime_ms':'review_runtime_ms'}[kind]
        used = ledger.db.execute('SELECT COALESCE(SUM(units),0) FROM review_actions WHERE review=? AND kind=?', (review, kind)).fetchone()[0]
        if time.time() - r['created'] > conf['review_runtime_ms']/1000 or used + units > conf[key]:
            return dict(proceed=False, reason='review_budget')
        ledger.db.execute('INSERT INTO review_actions VALUES (?,?,?,?,?)', (identity, review, kind, units, time.time()))
        return dict(proceed=True)


def register_rule(ledger, spec):
    if set(spec) != {'id','version','owner','expires','minimum','max_latency_increase_pct','max_human_increase_pct'}:
        raise Invalid('invalid rule spec fields')
    for k in ('id','version','owner'):
        label(spec[k], k)
    for k in ('expires','minimum','max_latency_increase_pct','max_human_increase_pct'):
        integer(spec[k], k)
    if spec['minimum'] < 1 or spec['expires'] <= time.time():
        raise Invalid('rule requires future expiry and positive sample minimum')
    with ledger.transaction():
        old = ledger.db.execute('SELECT spec FROM rules WHERE id=? AND version=?', (spec['id'], spec['version'])).fetchone()
        if old and json.loads(old[0]) != spec:
            raise Invalid('immutable rule version; register a new version')
        if not old:
            ledger.db.execute("INSERT INTO rules VALUES (?,?,?,'candidate',?)", (spec['id'],spec['version'],canonical(spec),time.time()))
            audit(ledger, 'rule.register', spec)
    return dict(registered=True)


def rule_state(ledger, rule, version, state, reason):
    if state not in ('active','disabled','retired','candidate'):
        raise Invalid('invalid rule state')
    label(reason, 'reason')
    with ledger.transaction():
        row = ledger.db.execute('SELECT spec FROM rules WHERE id=? AND version=?', (rule,version)).fetchone()
        if not row:
            raise Invalid('unknown rule')
        if state == 'active' and json.loads(row[0])['expires'] <= time.time():
            raise Invalid('expired rule needs a new version')
        if state == 'active':
            ledger.db.execute("UPDATE rules SET state='disabled' WHERE id=? AND version!=? AND state='active'",(rule,version))
        ledger.db.execute('UPDATE rules SET state=? WHERE id=? AND version=?', (state,rule,version))
        audit(ledger, 'rule.state', dict(rule=rule,version=version,state=state,reason=reason))
    return dict(state=state)


def current_version(ledger, rule):
    r = ledger.db.execute("SELECT version FROM rules WHERE id=? AND state='active' ORDER BY created DESC LIMIT 1",(rule,)).fetchone()
    return r[0] if r else None


def enabled(ledger, rule, version=None, task=None):
    if task and ledger.db.execute('SELECT 1 FROM exceptions WHERE task=? AND rule=? AND expires>?', (task,rule,time.time())).fetchone():
        return False
    r = ledger.db.execute('SELECT spec,state FROM rules WHERE id=? AND version=?', (rule,version or current_version(ledger,rule))).fetchone()
    return bool(r and r['state'] == 'active' and json.loads(r['spec'])['expires'] > time.time())


def exception(ledger, task, rule, expires, reason):
    label(task,'task'); label(rule,'rule'); label(reason,'reason'); integer(expires,'expires')
    if expires <= time.time() or not ledger.db.execute('SELECT 1 FROM rules WHERE id=?',(rule,)).fetchone():
        raise Invalid('exception requires known rule and future expiry')
    with ledger.transaction():
        ledger.db.execute('INSERT OR REPLACE INTO exceptions VALUES (?,?,?,?)',(task,rule,expires,reason))
        audit(ledger,'rule.exception',dict(task=task,rule=rule,expires=expires,reason=reason))
    return dict(recorded=True)


def intervention(ledger, identity, task, rule, version=None, policy='local', action='applied'):
    version = version or current_version(ledger,rule)
    for value in (identity, task, rule, version, policy):
        label(value, 'intervention field')
    if action not in ('applied','baseline','reverted'):
        raise Invalid('invalid intervention action')
    value = (task,rule,version,policy,action)
    old = ledger.db.execute('SELECT task,rule,version,policy,action FROM interventions WHERE id=?', (identity,)).fetchone()
    if old and tuple(old) != value:
        raise Invalid('intervention ID conflict')
    ledger.db.execute('INSERT OR IGNORE INTO interventions VALUES (?,?,?,?,?,?,?)', (identity,*value,time.time()))
    return dict(recorded=True)


def rule_report(ledger, rule, version, workload, baseline='baseline', treatment='treatment', attested=False, apply=False):
    from .metrics import compare
    row = ledger.db.execute('SELECT * FROM rules WHERE id=? AND version=?', (rule,version)).fetchone()
    if not row or baseline == treatment:
        raise Invalid('unknown rule or identical cohorts')
    spec = json.loads(row['spec'])
    groups = [ledger.events(workload, c) for c in (baseline,treatment)]
    result = compare(*groups, minimum=spec['minimum'], attested=attested)
    gaps = list(result['gaps'])
    for cohort, group, action in zip((baseline,treatment), groups, ('baseline','applied')):
        expected = {r[0] for r in ledger.db.execute('SELECT id FROM tasks WHERE workload=? AND cohort=?', (workload,cohort))}
        actual = {e['task_id'] for e in group if e['kind'] == 'usage' and e['purpose'] == 'execution'}
        overhead_only = {e['task_id'] for e in group if e['kind'] == 'usage' and e['purpose'] == 'overhead'} - actual
        expected -= overhead_only
        if not expected or actual != expected:
            gaps.append(f'{cohort}_registered_coverage_incomplete')
        for task in expected:
            exposures = list(ledger.db.execute('SELECT rule,version,action FROM interventions WHERE task=?', (task,)))
            if not any(tuple(r) == (rule,version,action) for r in exposures):
                gaps.append(f'{cohort}_missing_rule_assignment')
            if any((r['rule'],r['version']) != (rule,version) and r['action'] == 'applied' for r in exposures):
                gaps.append(f'{cohort}_multiple_controls_changed')
    outcomes = [[e for e in g if e['kind'] == 'outcome'] for g in groups]
    operational = {}
    for key, threshold in [('task_elapsed_ms', spec['max_latency_increase_pct']), ('human_ms', spec['max_human_increase_pct'])]:
        if any(not g or any(e.get(key) is None for e in g) for g in outcomes):
            gaps.append(f'{key}_unknown')
            continue
        means = [sum(e[key] for e in g)/len(g) for g in outcomes]
        operational[key] = dict(baseline_mean=means[0], treatment_mean=means[1], regression=means[1] > means[0]*(1+threshold/100))
    result.update(rule=rule, version=version, operational=operational, gaps=sorted(set(gaps)))
    if gaps:
        result.update(status='insufficient_evidence', estimated_net_savings_microusd=None)
    elif any(v['regression'] for v in operational.values()):
        result['status'] = 'operational_regression'
    harmful = result['status'] in ('quality_regression','operational_regression','no_observed_benefit')
    result['recommendation'] = 'disable' if harmful else 'retain_for_monitoring' if result['status'] == 'estimated_net_positive' else 'collect_evidence'
    result['disabled'] = False
    if apply and harmful:
        rule_state(ledger, rule, version, 'disabled', result['status'])
        result['disabled'] = True
    return result


def skill_run(ledger, raw):
    required = {'id','skill','version','task','kind','cost_microusd','saved_estimate_microusd','success','evidence'}
    if set(raw) != required or raw['kind'] not in ('use','build','maintenance') or type(raw['success']) is not bool:
        raise Invalid('invalid skill observation')
    for k in ('id','skill','version','task','evidence'):
        label(raw[k], k)
    for k in ('cost_microusd','saved_estimate_microusd'):
        integer(raw[k], k, nullable=True)
    with ledger.transaction():
        old = ledger.db.execute('SELECT data FROM skill_runs WHERE id=?', (raw['id'],)).fetchone()
        if old and json.loads(old[0]) != raw:
            raise Invalid('skill observation conflict')
        ledger.db.execute('INSERT OR IGNORE INTO skill_runs VALUES (?,?,?,?,?,?)',
                          (raw['id'],raw['skill'],raw['version'],raw['task'],canonical(raw),time.time()))
    return dict(recorded=True)


def skill_report(ledger, skill, version, idle_days=30):
    rows = list(ledger.db.execute('SELECT data,created FROM skill_runs WHERE skill=? AND version=?', (skill,version)))
    values = [json.loads(r[0]) for r in rows]
    uses = [v for v in values if v['kind'] == 'use']
    unknown = not values or any(v['cost_microusd'] is None or v['kind'] == 'use' and v['saved_estimate_microusd'] is None for v in values)
    net = None if unknown else sum(v['saved_estimate_microusd'] for v in uses) - sum(v['cost_microusd'] for v in values)
    idle = not uses or max(r['created'] for r in rows if json.loads(r['data'])['kind'] == 'use') < time.time()-idle_days*86400
    return dict(skill=skill,version=version,uses=len(uses),failures=sum(not v['success'] for v in uses),
                estimated_net_microusd=net, idle=idle, causal_proof=False,
                recommendation='review_for_retirement' if idle or net is not None and net <= 0 or any(not v['success'] for v in uses) else 'collect_evidence' if unknown else 'retain_for_monitoring')
