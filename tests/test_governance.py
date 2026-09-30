import concurrent.futures
import getpass
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from token_police import governance as g
from token_police.cli import main
from token_police.controls import DEFAULTS, hook, policy
from token_police.ledger import Invalid, Ledger
from token_police.optimizations import read_reference, json_select, retention, cache_report
from token_police.workflow import Workflow, collect, review_run
from test_core import usage, outcome


class Fixture:
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)
        self.db=Ledger(self.home/'ledger.sqlite3')
        self.org=dict(version='1',roles={g.principal_name():'admin'},limits=dict(project_microusd=1000,task_microusd=800,
             governor_microusd=200,reviews=2,inspections=1,notifications=1,review_runtime_ms=10000,cooldown_seconds=3600))
        g.register_task(self.db,'t','p','lint','treatment')

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def receipt(self,identity='u',cost=100,actor='worker'):
        return usage(identity,'t','treatment',cost,project_id='p',actor=actor)


class GovernanceTests(Fixture, unittest.TestCase):
    def test_governor_budget_is_shared_across_tasks(self):
        self.assertTrue(g.admit(self.db,'a','t',150,'governor',self.org,'issue')['dispatch'])
        g.register_task(self.db,'t2','p','lint','treatment')
        self.assertEqual(g.admit(self.db,'b','t2',100,'governor',self.org,'other')['reason'],'governor_budget')
        g.settle(self.db,'a',self.receipt(actor='governor',cost=150))
        self.assertEqual(g.admit(self.db,'c','t2',100,'governor',self.org,'other')['reason'],'governor_budget')

    def test_default_does_not_authorize_paid_governor(self):
        self.assertFalse(g.admit(self.db,'a','t',1,'governor',None,'issue')['dispatch'])

    def test_review_actions_and_replay_are_bounded(self):
        g.admit(self.db,'a','t',100,'governor',self.org,'issue')
        self.assertTrue(g.review_action(self.db,'x','a','inspection',1,self.org)['proceed'])
        self.assertFalse(g.review_action(self.db,'x','a','inspection',1,self.org)['proceed'])
        self.assertFalse(g.review_action(self.db,'y','a','inspection',1,self.org)['proceed'])
        self.assertTrue(g.review_action(self.db,'n','a','notification',1,self.org)['proceed'])
        self.assertFalse(g.review_action(self.db,'n2','a','notification',1,self.org)['proceed'])

    def test_cooldown_and_review_count(self):
        g.admit(self.db,'a','t',10,'governor',self.org,'issue')
        g.settle(self.db,'a',self.receipt(actor='governor',cost=10))
        self.assertEqual(g.admit(self.db,'b','t',10,'governor',self.org,'issue')['reason'],'issue_cooldown')
        g.admit(self.db,'b','t',10,'governor',self.org,'other')
        g.settle(self.db,'b',self.receipt('u2',10,'governor'))
        self.assertEqual(g.admit(self.db,'c','t',10,'governor',self.org,'third')['reason'],'review_limit')

    def test_concurrent_project_reservations_are_atomic(self):
        org={**self.org,'limits':{'project_microusd':100}}
        def dispatch(i):
            db=Ledger(self.db.path)
            try:
                return g.admit(db,str(i),'t',60,'worker',org)['dispatch']
            finally: db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(dispatch,range(6))),1)

    def test_unknown_billing_holds_next_call(self):
        g.admit(self.db,'a','t',100,'worker',self.org)
        g.settle(self.db,'a',self.receipt(cost=None))
        self.assertFalse(g.admit(self.db,'b','t',1,'worker',self.org)['dispatch'])

    def test_no_double_settlement_or_cross_actor_receipt(self):
        g.admit(self.db,'a','t',100,'governor',self.org,'i')
        with self.assertRaises(Invalid): g.settle(self.db,'a',self.receipt())
        g.settle(self.db,'a',self.receipt(actor='governor'))
        g.settle(self.db,'a',self.receipt(actor='governor'))
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM usage_index').fetchone()[0],1)
        with self.assertRaises(Invalid): g.settle(self.db,'a',self.receipt('other',actor='governor'))

    def test_project_limits_only_tighten(self):
        org={**self.org,'projects':{'p':{'project_microusd':9999,'reviews':100}}}
        self.assertEqual(g.limits(org,'p')['project_microusd'],1000)
        self.assertEqual(g.limits(org,'p')['reviews'],2)

    def test_roles_and_legacy_budget_bypass(self):
        org={**self.org,'roles':{g.principal_name():'viewer'}}
        g.authorize(org,'summary')
        with self.assertRaises(Invalid): g.authorize(org,'admit')
        with self.assertRaises(Invalid): g.authorize(self.org,'reserve')

    def test_central_limits_cannot_be_relaxed_by_local_config(self):
        p=self.home/'policy.json'; p.write_text(json.dumps(dict(mode='observe',read_lines=10000)))
        conf=policy(p,{'controls':dict(mode='enforce',read_lines=20)})
        self.assertEqual(conf['mode'],'enforce'); self.assertEqual(conf['read_lines'],20)

    def test_task_project_cannot_change(self):
        with self.assertRaises(Invalid): self.db.add(usage('x','t','treatment',1,project_id='other'))

    def test_workflow_records_response_automatically_and_replay_skips_callback(self):
        flow=Workflow(self.db,'t','p','lint','treatment',self.org)
        called=[]
        def callback():
            called.append(1)
            return {'id':'response1','model':'model','usage':{'input_tokens':10,'output_tokens':2,'input_tokens_details':{'cached_tokens':0}}}
        rates={'model':{'input':1,'output':1}}
        self.assertTrue(flow.call(callback,'a',100,'openai',rates)['dispatched'])
        self.assertFalse(flow.call(callback,'a',100,'openai',rates)['dispatched'])
        self.assertEqual(len(called),1)
        flow.outcome(True,'tests:passed',human_ms=0)
        self.assertEqual(g.coverage(self.db,'p')['tasks_with_known_cost'],1)

    def test_callback_failure_keeps_reservation_without_faking_receipt(self):
        flow=Workflow(self.db,'t','p','lint','treatment',self.org)
        def fail(): raise RuntimeError('provider disconnected')
        with self.assertRaises(RuntimeError): flow.call(fail,'a',700,'openai')
        self.assertFalse(g.admit(self.db,'b','t',101,'worker',self.org)['dispatch'])
        self.assertEqual(g.coverage(self.db,'p')['tasks_with_usage'],0)

    def test_collector_tracks_missing_source_and_incremental_receipts(self):
        path=self.home/'export.jsonl'
        manifest={'sources':[dict(path=str(path),task='t',project='p',workload='lint',cohort='treatment')]}
        self.assertEqual(collect(self.db,manifest)['sources'][0]['error'],'source_missing')
        path.write_text(json.dumps(self.receipt())+'\n')
        self.assertEqual(collect(self.db,manifest)['sources'][0]['added'],1)
        self.assertEqual(collect(self.db,manifest)['sources'][0]['added'],0)

    def test_audit_detects_modified_rows(self):
        self.assertTrue(g.audit_check(self.db)['valid'])
        self.db.db.execute("UPDATE audit SET data='{}' WHERE id=1")
        self.assertFalse(g.audit_check(self.db)['valid'])

    def test_retention_does_not_delete_billing_or_live_artifacts(self):
        self.db.add(self.receipt())
        old=self.home/'artifacts'/'old'; old.mkdir(parents=True); (old/'log').write_text('x')
        fresh=self.home/'artifacts'/'fresh'; fresh.mkdir()
        os.utime(old,(1,1))
        self.assertEqual(retention(self.db,1)['artifact_directories'],1)
        self.assertTrue(old.exists())
        retention(self.db,1,True)
        self.assertFalse(old.exists()); self.assertTrue(fresh.exists())
        self.assertEqual(len(self.db.events('lint','treatment')),1)

    def test_reference_reuse_is_invalidated_by_source_task_and_context(self):
        p=self.home/'source'; p.write_text('one\ntwo\nthree\n')
        first=read_reference(self.db,self.home,p,'t',lines=1)
        self.assertTrue(first['partial']); self.assertIn('content',first)
        second=read_reference(self.db,self.home,p,'t',lines=1)
        self.assertTrue(second['reused']); self.assertNotIn('content',second)
        self.assertFalse(read_reference(self.db,self.home,p,'different',lines=1)['reused'])
        self.assertFalse(read_reference(self.db,self.home,p,'t',lines=1,force=True)['reused'])
        p.write_text('changed\n')
        self.assertFalse(read_reference(self.db,self.home,p,'t',lines=1)['reused'])

    def test_reference_reopens_source_and_rejects_outside_root(self):
        p=self.home/'source'; p.write_text('x')
        read_reference(self.db,self.home,p,'t')
        p.unlink()
        with self.assertRaises(FileNotFoundError): read_reference(self.db,self.home,p,'t')
        sub=self.home/'sub'; sub.mkdir(); p.write_text('x')
        with self.assertRaises(Invalid): read_reference(self.db,sub,p,'t')

    def test_json_selection_preserves_exact_value_and_marks_partial(self):
        p=self.home/'a.json'; p.write_text(json.dumps({'a/b':[{'~key':7}],'other':'omitted'}))
        r=json_select(self.db,self.home,p,'/a~1b/0/~0key','t')
        self.assertEqual(r['value'],7); self.assertTrue(r['partial'])
        with self.assertRaises(Invalid): json_select(self.db,self.home,p,'/missing','t')

    def test_read_rule_retirement_and_exception(self):
        g.exception(self.db,'t','read_reference',int(time.time())+60,'owner needs original output')
        self.assertFalse(g.enabled(self.db,'read_reference',task='t'))
        self.assertTrue(g.enabled(self.db,'read_reference',task='other'))
        g.rule_state(self.db,'read_reference','1','retired','unused')
        self.assertFalse(g.enabled(self.db,'read_reference'))

    def test_disabled_hook_does_not_replay_old_rewrite(self):
        payload=dict(hook_event_name='PreToolUse',session_id='s',tool_use_id='c',tool_name='Read',tool_input={})
        conf={**DEFAULTS,'mode':'enforce'}
        self.assertIsNotNone(hook(self.db,payload,conf,'claude'))
        g.rule_state(self.db,'bounded_read','1','disabled','regression')
        self.assertIsNone(hook(self.db,payload,conf,'claude'))

    def test_new_rule_version_replaces_old_version(self):
        spec=dict(id='bounded_read',version='2',owner='test',expires=int(time.time())+100,minimum=1,max_latency_increase_pct=0,max_human_increase_pct=0)
        g.register_rule(self.db,spec); g.rule_state(self.db,'bounded_read','2','active','verified')
        self.assertEqual(g.current_version(self.db,'bounded_read'),'2')
        self.assertFalse(g.enabled(self.db,'bounded_read','1'))

    def test_observe_hook_errors_fail_open_and_enforce_errors_fail_closed(self):
        with patch('sys.stdin',io.StringIO('{"hook_event_name":"PreToolUse"}')),redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--home',str(self.home),'hook','--host','claude']),0)
        p=self.home/'policy.json'; p.write_text('{"mode":"enforce"}')
        with patch('sys.stdin',io.StringIO('{"hook_event_name":"PreToolUse"}')),redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--home',str(self.home),'--policy',str(p),'hook','--host','claude']),2)

    def test_review_process_missing_receipt_stays_held(self):
        r=review_run(self.db,[sys.executable,'-c','print("review")'],'t','a','issue',100,self.org,1)
        self.assertTrue(r['reservation_held']); self.assertFalse(r['settled'])

    def test_skill_reports_real_reuse_without_claiming_causal_savings(self):
        base=dict(skill='extract',version='1',task='t',success=True,evidence='receipt:1')
        g.skill_run(self.db,dict(base,id='build',kind='build',cost_microusd=100,saved_estimate_microusd=0))
        g.skill_run(self.db,dict(base,id='use',kind='use',cost_microusd=20,saved_estimate_microusd=50))
        r=g.skill_report(self.db,'extract','1')
        self.assertEqual(r['uses'],1); self.assertEqual(r['estimated_net_microusd'],-70)
        self.assertEqual(r['recommendation'],'review_for_retirement'); self.assertFalse(r['causal_proof'])

    def test_cache_unknown_does_not_become_zero(self):
        from token_police.ledger import validate
        e=validate(self.receipt()); e['cached_input_tokens']=None
        self.assertFalse(cache_report([e])['coverage_complete'])
        self.assertIsNone(cache_report([e])['cached_input_fraction'])


class RuleEvaluationTests(Fixture, unittest.TestCase):
    def populate(self,human=0,latency=10,cost=50,extra=False):
        spec=dict(id='test',version='1',owner='owner',expires=int(time.time())+100,minimum=1,max_latency_increase_pct=10,max_human_increase_pct=0)
        g.register_rule(self.db,spec); g.rule_state(self.db,'test','1','active','pilot')
        for task,cohort,amount in [('base','baseline',100),('t','treatment',cost)]:
            g.register_task(self.db,task,'p','lint',cohort)
            self.db.add(usage('u'+task,task,cohort,amount,project_id='p'))
            e=outcome('o'+task,task,cohort); e.update(project_id='p',human_ms=human if task=='t' else 0,task_elapsed_ms=latency if task=='t' else 10)
            self.db.add(e)
            g.intervention(self.db,'i'+task,task,'test','1',action='applied' if task=='t' else 'baseline')
        if extra:
            g.intervention(self.db,'extra','t','bounded_read','1')

    def test_rule_disables_on_human_regression(self):
        self.populate(human=1)
        r=g.rule_report(self.db,'test','1','lint',attested=True,apply=True)
        self.assertEqual(r['status'],'operational_regression'); self.assertTrue(r['disabled'])
        self.assertFalse(g.enabled(self.db,'test'))

    def test_mixed_interventions_cannot_claim_attribution(self):
        self.populate(extra=True)
        self.assertEqual(g.rule_report(self.db,'test','1','lint',attested=True)['status'],'insufficient_evidence')

    def test_absent_registered_task_blocks_positive_verdict(self):
        self.populate(); g.register_task(self.db,'missing','p','lint','treatment')
        self.assertEqual(g.rule_report(self.db,'test','1','lint',attested=True)['status'],'insufficient_evidence')

    def test_rule_disables_when_cost_increases(self):
        self.populate(cost=110)
        r=g.rule_report(self.db,'test','1','lint',attested=True,apply=True)
        self.assertEqual(r['status'],'no_observed_benefit'); self.assertTrue(r['disabled'])

    def test_beneficial_rule_stays_an_estimate(self):
        self.populate()
        r=g.rule_report(self.db,'test','1','lint',attested=True,apply=True)
        self.assertEqual(r['status'],'estimated_net_positive'); self.assertFalse(r['disabled']); self.assertFalse(r['causal_proof'])
