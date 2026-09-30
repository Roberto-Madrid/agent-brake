import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from token_police.adapters import normalizer
from token_police.cli import main
from token_police.controls import DEFAULTS, hook, policy, run_bounded
from token_police.governance import admit, exception, register_task
from token_police.ledger import Invalid, Ledger, validate
from token_police.optimizations import read_reference
from token_police.reporting import pilot_report, ranked_findings, reconcile, status
from test_core import usage, outcome


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Ledger(self.root/'ledger.sqlite3')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_status_distinguishes_missing_monitoring_from_no_findings(self):
        report = status(self.db, DEFAULTS)
        self.assertIsNone(report['spend_microusd'])
        self.assertFalse(report['hooks']['runtime_observed'])
        self.assertIn('hook trust', report['next_action'])
        hook(self.db, {'session_id':'s','hook_event_name':'SessionStart','_token_police_synthetic':True}, DEFAULTS,'codex')
        self.assertFalse(status(self.db, DEFAULTS)['hooks']['runtime_observed'])
        hook(self.db, {'session_id':'live','hook_event_name':'SessionStart'}, DEFAULTS,'codex')
        self.assertTrue(status(self.db, DEFAULTS)['hooks']['runtime_observed'])

    def test_status_unknown_cost_is_not_zero_and_budget_counts_reservations(self):
        register_task(self.db,'t','p','lint','baseline')
        org = {'limits':{'project_microusd':1000,'task_microusd':500}}
        self.db.add(usage(task='t',cost=100,project_id='p'))
        admit(self.db,'r','t',200,'worker',org)
        report = status(self.db,DEFAULTS,org,project='p',task='t')
        self.assertEqual(report['remaining_microusd'],200)
        self.assertEqual(report['unsettled_requests'],1)
        self.db.add(usage('missing',task='t',cost=None,project_id='p'))
        report = status(self.db,DEFAULTS,org,project='p',task='t')
        self.assertIsNone(report['remaining_microusd'])
        self.assertIsNone(report['spend_microusd'])
        self.assertEqual(report['known_subtotal_microusd'],100)

    def test_compaction_and_resume_invalidate_reference_reuse(self):
        source = self.root/'source'; source.write_text('important context')
        for host in ('codex','claude'):
            task = 'session:'+host
            self.assertFalse(read_reference(self.db,self.root,source,task)['reused'])
            self.assertTrue(read_reference(self.db,self.root,source,task)['reused'])
            for event in ('PreCompact','SessionStart'):
                hook(self.db,{'session_id':host,'hook_event_name':event},DEFAULTS,host)
                self.assertFalse(read_reference(self.db,self.root,source,task)['reused'])

    def test_long_unicode_line_continuation_returns_every_character(self):
        source = self.root/'source'; original = '€'*15000+'\nsecond\n'; source.write_bytes(original.encode())
        byte_offset = 0; fragments = []
        while True:
            result = read_reference(self.db,self.root,source,'t',lines=1,byte_offset=byte_offset)
            fragments.append(result['content'])
            self.assertLessEqual(len(result['content'].encode()),16000)
            if result['next_byte_offset'] is None:
                break
            self.assertEqual(result['next_offset'],0)
            byte_offset = result['next_byte_offset']
        self.assertEqual(''.join(fragments),'€'*15000+'\n')
        self.assertEqual(result['next_offset'],1)
        self.assertEqual(read_reference(self.db,self.root,source,'t',offset=1,lines=1)['content'],'second\n')
        with self.assertRaises(Invalid):
            read_reference(self.db,self.root,source,'t',lines=1,byte_offset=1)

    def test_adapter_omitted_cache_stays_unknown(self):
        for format_name in ('openai','anthropic'):
            with self.subTest(format_name=format_name):
                e = normalizer(format_name,'t','w','c',rates={'m':{'input':1,'output':2}})(
                    {'id':'a','model':'m','usage':{'input_tokens':100,'output_tokens':10}})
                self.assertIsNone(e['cached_input_tokens'])
                self.assertIsNone(e['cost_microusd'])
        e = normalizer('anthropic','t','w','c')({'id':'a','usage':{'input_tokens':100,'output_tokens':10}})
        self.assertIsNone(e['input_tokens'])

    def test_versioned_pricing_provenance_and_reconciliation(self):
        rates = {'version':'test-v1','effective_date':'2026-09-30','source_url':'https://example.org/pricing',
                 'models':{'m':{'input':1,'output':2}}}
        e = normalizer('openai','t','w','c',rates=rates)({'id':'a','model':'m',
            'usage':{'input_tokens':100,'output_tokens':10,'input_tokens_details':{'cached_tokens':0}}})
        self.assertEqual(e['cost_microusd'],120)
        self.assertTrue(e['pricing_version'].startswith('test-v1:'))
        validate(e)
        self.assertEqual(reconcile([e],{'billed_total_microusd':120,'evidence':'statement:1'})['status'],'matched')
        self.assertEqual(reconcile([e],{'billed_total_microusd':130,'evidence':'statement:1'})['difference_microusd'],10)
        e['cost_microusd']=None; e['cost_source']=None
        self.assertEqual(reconcile([e],{'billed_total_microusd':120,'evidence':'statement:1'})['status'],'insufficient_evidence')

    def test_findings_rank_evidence_without_guessing_savings(self):
        self.db.find('large_tool_output','a',{'bytes':80000,'tool':'Bash','action':'Bound output.'})
        self.db.find('repeated_failure','b',{'failures':4,'action':'Review inputs.'})
        findings = ranked_findings(self.db)
        self.assertEqual(findings[0]['code'],'repeated_failure')
        self.assertIn('run --max-output-bytes',findings[1]['suggested_command'])
        self.assertIsNone(findings[1]['estimated_avoided_cost_microusd'])

    def test_warning_and_expiring_exception_preserve_dispatch_limit(self):
        config = {**DEFAULTS,'mode':'enforce','max_session_tool_calls':2,'session_warning_pct':50}
        payload = {'session_id':'s','hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'command':'true'}}
        with patch.dict(os.environ,{'TOKEN_POLICE_TASK':'task'}):
            hook(self.db,{**payload,'tool_use_id':'1'},config,'codex')
            self.assertIn('session_budget_warning',[f['code'] for f in self.db.findings(100)])
            hook(self.db,{**payload,'tool_use_id':'2'},config,'codex')
            denied = hook(self.db,{**payload,'tool_use_id':'3'},config,'codex')
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'],'deny')
            exception(self.db,'task','session_call_limit',int(time.time())+60,'owner-approved necessary verification')
            self.assertIsNone(hook(self.db,{**payload,'tool_use_id':'3'},config,'codex'))
            self.db.db.execute('UPDATE exceptions SET expires=0')
            self.assertEqual(hook(self.db,{**payload,'tool_use_id':'4'},config,'codex')['hookSpecificOutput']['permissionDecision'],'deny')

    def test_pilot_report_includes_p95_and_missing_human_evidence(self):
        b = [validate(usage()),validate(outcome())]
        a = [validate(usage('a','a','treatment',500)),validate(outcome('o','a','treatment'))]
        result = pilot_report(b,a,1,True)
        self.assertFalse(result['release_evidence_complete'])
        b[1].update(task_elapsed_ms=100,human_ms=0); a[1].update(task_elapsed_ms=90,human_ms=0)
        result = pilot_report(b,a,1,True)
        self.assertTrue(result['release_evidence_complete'])
        self.assertEqual(result['operational']['task_elapsed_ms']['treatment']['p95'],90)

    def test_cli_status_on_fresh_state_is_actionable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--home',str(self.root),'status']),0)
        self.assertEqual(json.loads(output.getvalue())['receipt_count'],0)

    def test_timeout_terminates_descendant_before_it_writes(self):
        marker = self.root/'leaked-child'
        child = "import time; from pathlib import Path; time.sleep(2.5); Path("+repr(str(marker))+").write_text('leaked')"
        parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); time.sleep(30)'
        result = run_bounded([sys.executable,'-c',parent],self.root/'artifacts',timeout=1)
        self.assertTrue(result['timed_out'])
        time.sleep(2)
        self.assertFalse(marker.exists(),'Timed-out child escaped process-tree cleanup')


if __name__ == '__main__':
    unittest.main()
