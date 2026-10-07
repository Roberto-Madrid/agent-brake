import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def shell(self):
        command = shutil.which('sh')
        if not command and os.name == 'nt':
            command = str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/sh.exe')
            if not Path(command).exists(): command = None
        if not command:
            self.skipTest('Hook launcher requires a POSIX shell (Git Bash on Windows)')
        return command

    def test_configured_launcher_preserves_stdin_and_is_silent(self):
        shell = self.shell()
        with tempfile.TemporaryDirectory(prefix='token police ') as state:
            result = subprocess.run([sys.executable,str(ROOT/'scripts/setup.py'),'--home',state],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            env = dict(os.environ,TOKEN_POLICE_HOME=state)
            env.pop('TOKEN_POLICE_PYTHON',None)
            env.pop('TOKEN_POLICE_ORG_POLICY',None); env.pop('TOKEN_POLICE_POLICY',None)
            for host in ('codex','claude'):
                payload = {'hook_event_name':'PreToolUse','session_id':host,'tool_use_id':'probe',
                           'tool_name':'Bash','tool_input':{'command':'true'},'_token_police_synthetic':True}
                result = subprocess.run([shell,str(ROOT/'scripts/launch.sh'),'hook','--host',host],input=json.dumps(payload),
                                        capture_output=True,text=True,env=env)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,'')
            result = subprocess.run([sys.executable,str(ROOT/'scripts/tp.py'),'--home',state,'status'],capture_output=True,text=True,env=env)
            self.assertFalse(json.loads(result.stdout)['hooks']['runtime_observed'])

    def test_invalid_interpreter_override_is_actionable(self):
        shell = self.shell()
        with tempfile.TemporaryDirectory() as state:
            env = dict(os.environ,TOKEN_POLICE_HOME=state,TOKEN_POLICE_PYTHON=str(Path(state)/'missing interpreter'))
            result = subprocess.run([shell,str(ROOT/'scripts/launch.sh'),'doctor'],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,2)
            self.assertIn('Python 3.10+',result.stderr)
            self.assertEqual(result.stdout,'')

    def test_release_is_reproducible_and_archive_runs_without_checkout(self):
        with tempfile.TemporaryDirectory() as state:
            state = Path(state); output = state/'dist'
            command = [sys.executable,str(ROOT/'scripts/build_release.py'),'--output-dir',str(output)]
            subprocess.run(command,check=True,capture_output=True)
            before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
            subprocess.run(command,check=True,capture_output=True)
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()})
            for archive in output.glob('*.zip'):
                target = state/archive.stem
                with zipfile.ZipFile(archive) as bundle:
                    self.assertIn('scripts/launch.sh',bundle.namelist())
                    self.assertFalse(any('.git/' in name or 'ledger.sqlite3' in name or '__pycache__' in name for name in bundle.namelist()))
                    if '-anthropic-' in archive.name: self.assertIn('.claude-plugin/plugin.json',bundle.namelist())
                    bundle.extractall(target)
                result = subprocess.run([sys.executable,str(target/'scripts/tp.py'),'--home',str(state/'ledger'),'doctor'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['version'],'0.4.0')


if __name__ == '__main__':
    unittest.main()

