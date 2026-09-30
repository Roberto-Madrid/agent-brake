#!/usr/bin/env python3
"""Pin a checked interpreter in private state; never edit host trust/settings."""
import sys

if sys.version_info < (3, 10):
    sys.exit('Token Police requires Python 3.10+; rerun setup with a supported interpreter.')

import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--home', default=os.environ.get('TOKEN_POLICE_HOME') or os.environ.get('PLUGIN_DATA')
                    or os.environ.get('CLAUDE_PLUGIN_DATA') or str(Path.home()/'.token-police'))
args = parser.parse_args()
home = Path(args.home).resolve()
home.mkdir(parents=True, exist_ok=True, mode=0o700)
config = home/'python-path'
executable = str(Path(sys.executable).resolve())
if '\n' in executable or '\r' in executable:
    sys.exit('Interpreter path cannot contain newlines')
config.write_bytes((executable+'\n').encode('utf-8'))
config.chmod(0o600)
root = Path(__file__).resolve().parents[1]
result = subprocess.run([executable, str(root/'scripts/tp.py'), '--home', str(home), 'doctor'], check=False)
print(json.dumps({'configured': result.returncode == 0, 'python': executable, 'home': str(home),
                  'next_action': 'Set TOKEN_POLICE_HOME to this directory in the host environment; review hook trust, then run status after a harmless tool call.'}))
raise SystemExit(result.returncode)
