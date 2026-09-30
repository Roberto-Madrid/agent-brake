"""Instrument a caller-owned workflow; record final receipts without another model."""
import os
import time
import uuid
from pathlib import Path
from .adapters import normalizer
from .governance import admit, register_task, settle
from .ledger import Invalid


class Workflow:
    """Keep this object around one task; share IDs across children, not cumulative bills.

    Dispatch via call() to reserve spend and automatically settle a final provider
    response. The callback is supplied/authorized by the host, never by log content.
    Failed/uncertain requests retain their reservation until reconciled.
    """
    def __init__(self, ledger, task, project, workload, cohort, org=None):
        register_task(ledger, task, project, workload, cohort)
        self.ledger, self.task, self.project = ledger, task, project
        self.workload, self.cohort, self.org = workload, cohort, org
        self.started = time.monotonic()

    def call(self, callback, request_id, estimate_microusd, format_name, rates=None, actor='worker', issue=None, parent_request_id=None):
        decision = admit(self.ledger, request_id, self.task, estimate_microusd, actor, self.org, issue)
        if not decision['dispatch']:
            return {'dispatched': False, 'admission': decision}
        response = callback()  # Exceptions deliberately leave the admission held.
        raw = response.model_dump() if hasattr(response, 'model_dump') else response
        self.receipt(raw, request_id, format_name, rates, actor, parent_request_id)
        return {'dispatched': True, 'response': response}

    def receipt(self, raw, request_id, format_name='canonical', rates=None, actor='worker', parent_request_id=None):
        event = normalizer(format_name, self.task, self.workload, self.cohort, actor, rates)(raw)
        if event is None:
            raise Invalid('callback did not return a final usage receipt')
        event.update(project_id=self.project, request_id=request_id)
        if parent_request_id:
            event['parent_request_id'] = parent_request_id
        return settle(self.ledger, request_id, event)

    def outcome(self, accepted, evidence, rework_count=0, human_ms=None):
        if type(accepted) is not bool:
            raise Invalid('acceptance must come from explicit external verification')
        return self.ledger.add(dict(schema_version=1, event_id=f'outcome:{self.task}',kind='outcome',
            task_id=self.task, project_id=self.project, workload=self.workload, cohort=self.cohort,
            status='accepted' if accepted else 'failed', evidence=evidence,rework_count=rework_count,
            task_elapsed_ms=round((time.monotonic()-self.started)*1000),human_ms=human_ms))


def collect(ledger, manifest):
    """One bounded incremental pass; invoke on workflow completion or host scheduler."""
    if not isinstance(manifest, dict) or set(manifest) != {'sources'} or not isinstance(manifest['sources'], list) or len(manifest['sources']) > 32:
        raise Invalid('collector requires at most 32 explicit sources')
    results = []
    for source in manifest['sources']:
        if set(source) - {'path','format','task','project','workload','cohort','rates','actor'}:
            raise Invalid('unknown collector source field')
        path = Path(source['path'])
        if not path.is_absolute():
            raise Invalid('collector paths must be absolute')
        register_task(ledger, source['task'], source['project'], source['workload'], source['cohort'])
        convert = normalizer(source.get('format','canonical'), source['task'], source['workload'], source['cohort'],source.get('actor','worker'),source.get('rates'))
        def convert_project(raw):
            e = convert(raw)
            if e is not None:
                if (e['task_id'],e['workload'],e['cohort']) != (source['task'],source['workload'],source['cohort']):
                    raise Invalid('source task does not match manifest')
                if e.get('project_id',source['project']) != source['project']:
                    raise Invalid('source project mismatch')
                e['project_id'] = source['project']
            return e
        try:
            results.append(dict(task=source['task'], **ledger.ingest(path, convert_project, batch=1000)))
        except FileNotFoundError:
            results.append(dict(task=source['task'],error='source_missing'))
    return dict(sources=results, llm_calls=0)


def review_run(ledger, command, task, identity, issue, estimate, org, timeout=60):
    """Bound an explicitly requested reviewer process. Never invoked by monitoring."""
    from .controls import run_bounded
    from .governance import limits, review_action
    decision = admit(ledger, identity, task, estimate, 'governor', org, issue)
    if not decision['dispatch']:
        return dict(dispatched=False,admission=decision)
    project=ledger.db.execute('SELECT project FROM tasks WHERE id=?',(task,)).fetchone()[0]
    conf=limits(org,project)
    if not review_action(ledger,identity+':runtime',identity,'runtime_ms',min(timeout*1000,conf['review_runtime_ms']),org)['proceed']:
        from .governance import release
        release(ledger,identity)
        return dict(dispatched=False,reason='review_runtime_budget')
    receipt=ledger.path.parent/('review-'+uuid.uuid4().hex+'.json')
    env={**os.environ,'TOKEN_POLICE_REVIEW_ID':identity,'TOKEN_POLICE_TASK':task,
         'TOKEN_POLICE_RECEIPT_FILE':str(receipt),'TOKEN_POLICE_HOME':str(ledger.path.parent)}
    allowed_timeout=min(timeout,conf['review_runtime_ms']//1000)
    if allowed_timeout < 1:
        from .governance import release
        release(ledger,identity)
        return dict(dispatched=False,reason='review_runtime_budget')
    result=run_bounded(command,ledger.path.parent/'artifacts',timeout=allowed_timeout,env=env)
    settled=False
    if receipt.exists():
        import json
        with receipt.open() as stream:
            data=stream.read(2*1024*1024+1)
        if len(data.encode()) > 2*1024*1024:
            raise Invalid('review receipt too large; reservation held')
        settle(ledger,identity,json.loads(data))
        receipt.unlink()
        settled=True
    return dict(dispatched=True,settled=settled,reservation_held=not settled,run=result)


def cycle(ledger, manifest, apply=False):
    """One bounded collect/evaluate cycle, suitable for a trusted runner job."""
    from .governance import rule_report
    if not isinstance(manifest,dict) or set(manifest) != {'sources','evaluations'} or not isinstance(manifest['evaluations'],list) or len(manifest['evaluations']) > 10:
        raise Invalid('cycle requires sources and at most ten explicit evaluations')
    imported=collect(ledger,{'sources':manifest['sources']})
    reports=[]
    for config in manifest['evaluations']:
        if set(config) != {'rule','version','workload','baseline','treatment','attest_complete'} or type(config['attest_complete']) is not bool:
            raise Invalid('invalid evaluation contract')
        reports.append(rule_report(ledger,config['rule'],config['version'],config['workload'],config['baseline'],config['treatment'],config['attest_complete'],apply))
    return dict(collection=imported,evaluations=reports,llm_calls=0)
