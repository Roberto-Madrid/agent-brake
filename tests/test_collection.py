"""OTel receipts, collector failure, evaluation application, and governor allowances."""
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_core import outcome, usage
from token_police.adapters import normalizer
from token_police.cli import main
from token_police.governance import admit, enabled, intervention, principal_name, register_rule, register_task, release, rule_state, settle
from token_police.ledger import Invalid, Ledger
from token_police.workflow import collect, cycle

ROOT = Path(__file__).resolve().parents[1]


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.db = Ledger(self.home / 'ledger.sqlite3')
        self.org = dict(version='1', roles={principal_name(): 'admin'}, limits=dict(
            project_microusd=1000, task_microusd=800, governor_microusd=200, reviews=1,
            inspections=1, notifications=1, review_runtime_ms=10000, cooldown_seconds=3600))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_otel_fixture_keeps_known_cost_and_unknown_fields(self):
        manifest = {'sources': [dict(path=str(ROOT / 'examples' / 'otel.jsonl'), format='otel',
                                     task='t', project='p', workload='lint', cohort='treatment')]}
        imported = collect(self.db, manifest)
        self.assertEqual(imported['llm_calls'], 0)
        self.assertEqual(imported['sources'][0]['added'], 3)
        events = {e['event_id']: e for e in self.db.events('lint', 'treatment')}
        self.assertEqual(events['otel:tr-billed:sp-billed']['cost_microusd'], 100)
        opened = events['otel:tr-open:sp-open']
        self.assertIsNone(opened['cost_microusd'])
        self.assertIsNone(opened['cached_input_tokens'])
        self.assertIsNone(opened['cache_write_tokens'])
        cost_only = events['otel:tr-cost-only:sp-cost-only']
        self.assertEqual(cost_only['cost_microusd'], 50)
        self.assertIsNone(cost_only['input_tokens'])
        self.assertIsNone(cost_only['output_tokens'])
        register_task(self.db, 't', 'p', 'lint', 'treatment')
        self.assertEqual(admit(self.db, 'next', 't', 1, 'worker', self.org)['reason'], 'project_cost_unknown')

    def test_cost_only_span_reduces_remaining_project_budget(self):
        path = self.home / 'cost.jsonl'
        span = dict(trace_id='tr', span_id='sp', attributes={
            'token_police.cost_microusd': 80, 'token_police.cost_source': 'billed'})
        path.write_text(json.dumps(span) + '\n')
        org = {**self.org, 'limits': {**self.org['limits'], 'project_microusd': 100, 'task_microusd': 100}}
        collect(self.db, {'sources': [dict(path=str(path), format='otel', task='t', project='p',
                                            workload='lint', cohort='treatment')]})
        self.assertEqual(admit(self.db, 'next', 't', 30, 'worker', org)['reason'], 'project_budget')

    def test_missing_cache_is_not_priced_as_zero(self):
        span = dict(trace_id='tr', span_id='sp', attributes={
            'gen_ai.response.model': 'fixture-model', 'gen_ai.usage.input_tokens': 1000,
            'gen_ai.usage.output_tokens': 10})
        event = normalizer('otel', 't', 'lint', 'treatment', rates={
            'fixture-model': {'input': 2, 'output': 10, 'cache_read': 0.2}})(span)
        self.assertIsNone(event['cached_input_tokens'])
        self.assertIsNone(event['cost_microusd'])
        self.assertIsNone(event['cost_source'])

    def test_retry_spans_stay_separate_charges(self):
        lines = [dict(trace_id='same', span_id=span, attributes={
            'gen_ai.usage.input_tokens': 10, 'gen_ai.usage.output_tokens': 1,
            'token_police.cached_input_tokens': 0, 'token_police.cache_write_tokens': 0,
            'token_police.cost_microusd': 40, 'token_police.cost_source': 'billed'}) for span in ('a', 'b')]
        path = self.home / 'retries.jsonl'
        path.write_text(''.join(json.dumps(line) + '\n' for line in lines))
        added = self.db.ingest(path, normalizer('otel', 't', 'lint', 'treatment'))['added']
        self.assertEqual(added, 2)
        self.assertEqual(sum(e['cost_microusd'] for e in self.db.events('lint', 'treatment')), 80)

    def test_envelope_batch_and_aggregate_do_not_advance_as_empty(self):
        path = self.home / 'bad.jsonl'
        rejects = (
            {'resourceSpans': [{'scopeSpans': []}]},
            {'trace_id': 'tr', 'span_id': 'sp', 'spans': [{'span_id': 'child'}], 'attributes': {
                'gen_ai.usage.input_tokens': 1, 'gen_ai.usage.output_tokens': 1}},
            {'trace_id': 'tr', 'span_id': 'sp', 'attributes': {
                'token_police.aggregate': True, 'token_police.cost_microusd': 90,
                'token_police.cost_source': 'billed'}},
        )
        for raw in rejects:
            path.write_text(json.dumps(raw) + '\n')
            with self.subTest(raw=sorted(raw)), self.assertRaises(Invalid):
                self.db.ingest(path, normalizer('otel', 't', 'lint', 'treatment'))
            self.assertEqual(self.db.events('lint', 'treatment'), [])

    def test_non_usage_span_is_skipped_and_a_later_charge_remains(self):
        path = self.home / 'mixed.jsonl'
        skipped = dict(trace_id='tr', span_id='http', attributes={'http.method': 'GET'})
        billed = dict(trace_id='tr', span_id='gen', attributes={
            'token_police.cost_microusd': 15, 'token_police.cost_source': 'billed'})
        path.write_text(json.dumps(skipped) + '\n' + json.dumps(billed) + '\n')
        result = self.db.ingest(path, normalizer('otel', 't', 'lint', 'treatment'))
        self.assertEqual(result['added'], 1)
        self.assertEqual(self.db.events('lint', 'treatment')[0]['cost_microusd'], 15)

    def test_invalid_record_rolls_back_the_collector_batch(self):
        path = self.home / 'export.jsonl'
        good = usage('u', 't', 'treatment', 10, project_id='p')
        path.write_text(json.dumps(good) + '\n{bad\n')
        manifest = {'sources': [dict(path=str(path), task='t', project='p', workload='lint', cohort='treatment')]}
        with self.assertRaises(Invalid):
            collect(self.db, manifest)
        self.assertEqual(self.db.events('lint', 'treatment'), [])
        path.write_text(json.dumps(good) + '\n')
        self.assertEqual(collect(self.db, manifest)['sources'][0]['added'], 1)

    def test_collector_rejects_relative_path_and_identity_mismatch(self):
        with self.assertRaises(Invalid):
            collect(self.db, {'sources': [dict(path='export.jsonl', task='t', project='p', workload='lint', cohort='treatment')]})
        path = self.home / 'export.jsonl'
        path.write_text(json.dumps(usage('u', 'other', 'treatment', 10, project_id='p')) + '\n')
        manifest = {'sources': [dict(path=str(path), task='t', project='p', workload='lint', cohort='treatment')]}
        with self.assertRaises(Invalid):
            collect(self.db, manifest)
        path.write_text(json.dumps(usage('u', 't', 'treatment', 10, project_id='other')) + '\n')
        with self.assertRaises(Invalid):
            collect(self.db, manifest)
        self.assertEqual(self.db.events('lint', 'treatment'), [])

    def test_worker_spend_does_not_consume_governor_allowance(self):
        register_task(self.db, 't', 'p', 'lint', 'treatment')
        org = {**self.org, 'limits': {**self.org['limits'], 'project_microusd': 5000, 'task_microusd': 5000, 'reviews': 2}}
        self.assertTrue(admit(self.db, 'w', 't', 1000, 'worker', org)['dispatch'])
        settle(self.db, 'w', usage('uw', 't', 'treatment', 1000, project_id='p'))
        self.assertTrue(admit(self.db, 'g', 't', 200, 'governor', org, 'issue')['dispatch'])

    def test_released_governor_admission_frees_allowance(self):
        register_task(self.db, 't', 'p', 'lint', 'treatment')
        self.assertTrue(admit(self.db, 'a', 't', 80, 'governor', self.org, 'one')['dispatch'])
        self.assertFalse(admit(self.db, 'b', 't', 80, 'governor', self.org, 'two')['dispatch'])
        release(self.db, 'a')
        self.assertTrue(admit(self.db, 'c', 't', 80, 'governor', self.org, 'three')['dispatch'])

    def test_governor_spend_counts_against_the_project_budget(self):
        register_task(self.db, 't', 'p', 'lint', 'treatment')
        org = {**self.org, 'limits': {**self.org['limits'], 'project_microusd': 200, 'task_microusd': 200, 'reviews': 2}}
        self.assertTrue(admit(self.db, 'g', 't', 150, 'governor', org, 'issue')['dispatch'])
        settle(self.db, 'g', usage('ug', 't', 'treatment', 150, project_id='p', actor='governor'))
        self.assertEqual(admit(self.db, 'w', 't', 60, 'worker', org)['reason'], 'project_budget')

    def _arm_rule(self, cost, missing=False):
        spec = dict(id='pilot', version='1', owner='owner', expires=int(time.time()) + 100,
                    minimum=1, max_latency_increase_pct=10, max_human_increase_pct=0)
        register_rule(self.db, spec)
        rule_state(self.db, 'pilot', '1', 'active', 'pilot')
        for task, cohort, amount in (('base', 'baseline', 100), ('t', 'treatment', cost)):
            register_task(self.db, task, 'p', 'lint', cohort)
            self.db.add(usage('u' + task, task, cohort, amount, project_id='p'))
            finished = outcome('o' + task, task, cohort)
            finished.update(project_id='p', human_ms=0, task_elapsed_ms=10)
            self.db.add(finished)
            intervention(self.db, 'i' + task, task, 'pilot', '1', action='applied' if task == 't' else 'baseline')
        if missing:
            register_task(self.db, 'missing', 'p', 'lint', 'treatment')

    def _cycle(self, apply):
        manifest = {
            'sources': [dict(path=str(self.home / 'absent.jsonl'), task='t', project='p', workload='lint', cohort='treatment')],
            'evaluations': [dict(rule='pilot', version='1', workload='lint', baseline='baseline', treatment='treatment', attest_complete=True)],
        }
        return cycle(self.db, manifest, apply)

    def test_cycle_apply_disables_a_harmful_rule_and_report_does_not(self):
        self._arm_rule(110)
        report = self._cycle(False)
        self.assertEqual(report['llm_calls'], 0)
        self.assertEqual(report['collection']['sources'][0]['error'], 'source_missing')
        evaluation = report['evaluations'][0]
        self.assertEqual(evaluation['status'], 'no_observed_benefit')
        self.assertFalse(evaluation['causal_proof'])
        self.assertFalse(evaluation['disabled'])
        self.assertLessEqual(evaluation['estimated_net_savings_microusd'], 0)
        self.assertTrue(enabled(self.db, 'pilot'))
        applied = self._cycle(True)
        self.assertTrue(applied['evaluations'][0]['disabled'])
        self.assertFalse(enabled(self.db, 'pilot'))

    def test_cycle_missing_receipt_does_not_disable_or_claim_savings(self):
        self._arm_rule(50, missing=True)
        applied = self._cycle(True)
        evaluation = applied['evaluations'][0]
        self.assertEqual(evaluation['status'], 'insufficient_evidence')
        self.assertIsNone(evaluation['estimated_net_savings_microusd'])
        self.assertFalse(evaluation['disabled'])
        self.assertTrue(enabled(self.db, 'pilot'))
        self.assertIn('treatment_registered_coverage_incomplete', evaluation['gaps'])

    def test_org_controls_survive_a_looser_local_policy_at_the_launcher(self):
        org = self.home / 'org.json'
        org.write_text(json.dumps(dict(version='1', roles={principal_name(): 'admin'},
                                       controls=dict(mode='enforce', read_lines=20))))
        os.chmod(org, 0o600)
        local = self.home / 'local.json'
        local.write_text(json.dumps(dict(mode='observe', read_lines=10000)))
        payload = json.dumps(dict(hook_event_name='PreToolUse', session_id='s', tool_use_id='c',
                                   tool_name='Read', tool_input={}))
        out = io.StringIO()
        with patch('sys.stdin', io.StringIO(payload)), redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(['--home', str(self.home), '--policy', str(local), '--org-policy', str(org), 'hook', '--host', 'claude'])
        self.assertEqual(code, 0)
        decision = json.loads(out.getvalue())
        self.assertEqual(decision['hookSpecificOutput']['updatedInput']['limit'], 20)
        self.assertNotIn('permissionDecision', decision['hookSpecificOutput'])
