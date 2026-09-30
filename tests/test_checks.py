"""Fleet gates as scripts, and repeat findings that do not create skills."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from token_police.checks import diffstat, gate_exit, secret_names, skill_budget
from token_police.cli import main
from token_police.controls import DEFAULTS, hook
from token_police.ledger import Ledger
from token_police.metrics import skill_payback


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gate_exit_records_code_without_a_block_decision(self):
        failed = gate_exit([sys.executable, '-c', 'raise SystemExit(7)'], self.home)
        self.assertEqual(failed['verdict'], 'fail')
        self.assertEqual(failed['exit_code'], 7)
        self.assertEqual(failed['judgment'], 'not_automated')
        self.assertEqual(failed['billing_savings'], 'unknown')
        self.assertNotIn('preview', json.dumps(failed))
        passed = gate_exit([sys.executable, '-c', 'raise SystemExit(0)'], self.home)
        self.assertEqual(passed['verdict'], 'pass')

    def test_diffstat_caps_paths_and_omits_patch_text(self):
        root = self.home / 'repo'
        root.mkdir()
        subprocess.check_call(['git', 'init'], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call(['git', 'config', 'user.email', 'test@example.com'], cwd=root)
        subprocess.check_call(['git', 'config', 'user.name', 'Test'], cwd=root)
        (root / 'a.txt').write_text('a')
        subprocess.check_call(['git', 'add', 'a.txt'], cwd=root)
        subprocess.check_call(['git', 'commit', '-m', 'base'], cwd=root, stdout=subprocess.DEVNULL)
        (root / 'a.txt').write_text('secret-line-should-not-appear')
        (root / 'b.txt').write_text('b')
        (root / 'c.txt').write_text('c')
        result = diffstat(root, 1)
        self.assertEqual(result['verdict'], 'over_cap')
        self.assertEqual(result['path_count'], 3)
        self.assertEqual(len(result['paths']), 1)
        self.assertEqual(result['omitted'], 2)
        self.assertNotIn('secret-line-should-not-appear', json.dumps(result))
        self.assertEqual(diffstat(self.home, 5)['verdict'], 'unknown')

    def test_secret_names_lists_filenames_and_does_not_read_values(self):
        (self.home / '.env').write_text('API_KEY=super-secret-value')
        (self.home / 'notes.txt').write_text('super-secret-value')
        (self.home / 'keep.pem').write_text('not-a-value-to-print')
        result = secret_names(self.home)
        self.assertEqual(result['values_read'], False)
        self.assertIn('.env', result['names'])
        self.assertIn('keep.pem', result['names'])
        self.assertNotIn('notes.txt', result['names'])
        encoded = json.dumps(result)
        self.assertNotIn('super-secret-value', encoded)
        self.assertNotIn('not-a-value-to-print', encoded)

    def test_skill_budget_matches_the_package_word_cap(self):
        path = self.home / 'SKILL.md'
        path.write_text('one two three')
        self.assertFalse(skill_budget(path, 3)['over'])
        self.assertTrue(skill_budget(path, 2)['over'])
        self.assertEqual(skill_budget(path)['billing_savings'], 'unknown')

    def test_deterministic_repeat_is_not_a_skill_candidate(self):
        candidate = dict(expected_uses=20, saved_units_per_use=100, load_units_per_use=10,
                         build_units=50, maintenance_units=0, stable_workflow=True,
                         needs_judgment=False, no_existing_fit=True, unit='estimated_tokens')
        result = skill_payback(candidate)
        self.assertEqual(result['verdict'], 'defer_or_use_simpler_mechanism')
        self.assertFalse(result['auto_create'])

    def test_successful_repeat_is_a_finding_and_creates_no_skill(self):
        ledger = Ledger(self.home / 'ledger.sqlite3')
        skills = self.home / 'skills'
        skills.mkdir()
        conf = {**DEFAULTS, 'mode': 'enforce', 'repeat_success_after': 2}
        payload = dict(hook_event_name='PostToolUse', tool_name='Bash', tool_input={'command': 'git diff --shortstat'},
                       tool_response={'ok': True})

        def repeat(session, call):
            self.assertIsNone(hook(ledger, dict(payload, session_id=session, tool_use_id=call), conf, 'claude'))

        repeat('s1', 'a')
        repeat('s1', 'b')
        self.assertFalse(any(item['code'] == 'repeatable_action' for item in ledger.findings(10)))
        repeat('s2', 'c')
        found = [item for item in ledger.findings(10) if item['code'] == 'repeatable_action']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['billing_savings'], 'unknown')
        self.assertNotIn('command', json.dumps(found))
        self.assertEqual(list(skills.iterdir()), [])
        repeat('s3', 'd')
        self.assertEqual(len([item for item in ledger.findings(10) if item['code'] == 'repeatable_action']), 1)
        ledger.close()

    def test_cli_gate_exit_preserves_failure_status(self):
        with redirect_stdout(io.StringIO()):
            code = main(['--home', str(self.home), 'gate-exit', '--', sys.executable, '-c', 'raise SystemExit(4)'])
        self.assertEqual(code, 4)
