"""Small deterministic reports; unknown evidence stays explicit."""
import json
import math
import time
from .governance import coverage, limits
from .ledger import Invalid, integer
from .metrics import compare


def ranked_findings(ledger):
    findings = [{'id': r['id'], 'code': r['code'], 'data': json.loads(r['data']), 'created': r['created']}
                for r in ledger.db.execute('SELECT * FROM findings WHERE resolved=0 ORDER BY created DESC LIMIT 100')]
    weights = {'session_call_limit': 5, 'repeated_failure': 4, 'large_model_input': 3,
               'large_tool_output': 3, 'session_budget_warning': 2, 'repeatable_action': 1, 'bounded_read': 1}
    for finding in findings:
        data = finding['data']
        finding['priority'] = weights.get(finding['code'], 1)
        finding['evidence'] = data
        finding['estimated_avoided_cost_microusd'] = None
        if finding['code'] == 'large_tool_output':
            finding['suggested_command'] = 'token-police run --max-output-bytes 12000 -- <original executable and arguments>'
        elif finding['code'] == 'large_model_input':
            finding['suggested_command'] = 'token-police read-reference --root <allowed root> --file <source> --task <task>'
    return sorted(findings, key=lambda f: (-f['priority'], -f['created']))


def status(ledger, config, org=None, project=None, task=None):
    if task:
        registered = ledger.db.execute('SELECT project FROM tasks WHERE id=?',(task,)).fetchone()
        if registered:
            if project and project != registered[0]:
                raise Invalid('task does not belong to the selected project')
            project = registered[0]
    where, params = [], []
    if project:
        where.append('project=?'); params.append(project)
    if task:
        where.append('task=?'); params.append(task)
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    costs = list(ledger.db.execute('SELECT cost FROM usage_index'+clause, params))
    unknown = sum(r[0] is None for r in costs)
    partial = sum(r[0] for r in costs if r[0] is not None)
    pending = list(ledger.db.execute("SELECT task,project,estimate FROM admissions WHERE status='active'"))
    pending = [r for r in pending if (not project or r['project'] == project) and (not task or r['task'] == task)]
    legacy = list(ledger.db.execute("SELECT task_id,estimate FROM reservations WHERE status='active'"))
    # A project report can attribute legacy task reservations only through registration.
    project_tasks = {r[0] for r in ledger.db.execute('SELECT id FROM tasks WHERE project=?',(project,))} if project else None
    legacy = [r for r in legacy if (not task or r['task_id'] == task) and (project_tasks is None or r['task_id'] in project_tasks)]
    held = sum(r['estimate'] for r in pending) + sum(r['estimate'] for r in legacy)
    conf = limits(org, project)
    cap = conf['task_microusd'] if task else conf['project_microusd'] if project else None
    total = None if unknown or not costs else partial
    hooks = [dict(r) for r in ledger.db.execute('SELECT * FROM hook_health ORDER BY last_seen DESC LIMIT 20')]
    observed = any(not r['synthetic'] for r in hooks)
    findings = ranked_findings(ledger)
    rules = [dict(r) for r in ledger.db.execute('SELECT id,version,state,spec FROM rules')]
    for rule in rules:
        rule['expired'] = json.loads(rule.pop('spec'))['expires'] <= time.time()
    exceptions = [dict(r) for r in ledger.db.execute('SELECT * FROM exceptions WHERE expires>?',(time.time(),))]
    next_action = ('Import final usage receipts; tool hooks do not supply model billing.' if not costs else
                   'Resolve missing cost evidence before making savings claims.' if unknown else
                   findings[0]['data'].get('action', 'Review the highest priority finding.') if findings else
                   'Record externally verified task outcomes and compare a bounded pilot.')
    if not observed:
        next_action = 'Review host hook trust, run a harmless tool call, then check status. ' + next_action
    return {'mode': config['mode'], 'scope': {'project': project, 'task': task},
            'spend_microusd': total, 'known_subtotal_microusd': partial, 'unknown_cost_receipts': unknown,
            'receipt_count': len(costs), 'reserved_microusd': held, 'unsettled_requests': len(pending)+len(legacy),
            'budget_cap_microusd': cap, 'remaining_microusd': None if cap is None or unknown else max(0, cap-partial-held),
            'hooks': {'runtime_observed': observed, 'trust': 'not_inspected', 'recent': hooks,
                      'coverage': 'local supported tool paths only; model requests and hosted tools require separate receipts'},
            'coverage': coverage(ledger, project) if project else None, 'controls': rules,
            'exceptions': exceptions, 'findings': findings[:5], 'next_action': next_action,
            'llm_calls': 0, 'network_calls': 0}


def reconcile(events, statement):
    if not isinstance(statement, dict) or set(statement) != {'billed_total_microusd','evidence'}:
        raise Invalid('statement requires billed_total_microusd and evidence for the selected workload/cohort')
    integer(statement['billed_total_microusd'], 'billed total')
    from .ledger import label
    label(statement['evidence'], 'statement evidence')
    usage = [e for e in events if e['kind'] == 'usage']
    unknown = sum(e['cost_microusd'] is None for e in usage)
    total = sum(e['cost_microusd'] for e in usage if e['cost_microusd'] is not None)
    gap = statement['billed_total_microusd']-total
    return {'status': 'insufficient_evidence' if unknown or not usage else 'matched' if gap == 0 else 'mismatch',
            'logged_subtotal_microusd': total, 'billed_total_microusd': statement['billed_total_microusd'],
            'difference_microusd': gap, 'unknown_cost_receipts': unknown, 'evidence': statement['evidence'],
            'scope_attested_by_operator': True, 'receipts_modified': False,
            'request_coverage_proven': False}


def pilot_report(before, after, minimum=5, attested=False):
    result = compare(before, after, minimum, attested)
    operational = {}
    for key in ('task_elapsed_ms','human_ms'):
        groups = [[e.get(key) for e in events if e['kind'] == 'outcome'] for events in (before,after)]
        stats = []
        for values in groups:
            if not values or any(v is None for v in values):
                stats.append({'mean': None, 'p95': None})
            else:
                values.sort()
                stats.append({'mean': sum(values)/len(values), 'p95': values[math.ceil(.95*len(values))-1]})
        operational[key] = dict(zip(('baseline','treatment'), stats))
    result['operational'] = operational
    result['release_evidence_complete'] = not result['gaps'] and all(
        s['mean'] is not None for groups in operational.values() for s in groups.values())
    result['next_action'] = 'Review quality, latency and human effort before retaining the control.' if result['release_evidence_complete'] else 'Collect missing billing, outcome, latency or human-effort evidence.'
    return result
