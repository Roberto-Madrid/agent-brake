#!/usr/bin/env python3
"""Read-only native host checks. No installs, trust changes, or model calls."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--claude')
parser.add_argument('--codex')
args = parser.parse_args()
if not args.claude and not args.codex:
    parser.error('provide --claude or --codex executable')
results = {}

def run(command):
    result = subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout or result.stderr)
    return json.loads(result.stdout)

if args.claude:
    results['claude_marketplace'] = run([args.claude,'plugin','validate','--strict','--json',str(root)])
    with tempfile.TemporaryDirectory(prefix='token-police-host-') as state:
        stage = Path(state)/'plugin'
        shutil.copytree(root,stage,ignore=shutil.ignore_patterns('.git','.agents','dist','__pycache__','marketplace.json'))
        results['claude_plugin'] = run([args.claude,'plugin','validate','--strict','--json',str(stage)])
    assert results['claude_plugin']['success'] and results['claude_marketplace']['success']
if args.codex:
    response = run([args.codex,'plugin','list','--available','--json','--marketplace','token-police-private',
                    '-c','marketplaces.token-police-private.source_type="local"',
                    '-c','marketplaces.token-police-private.source='+json.dumps(root.as_posix())])
    matches = [p for p in response['available'] if p['name'] == 'token-police']
    assert len(matches) == 1 and matches[0]['version'] == json.loads((root/'plugin.json').read_text())['version']
    results['codex_catalog'] = {'recognized':True,'version':matches[0]['version']}
print(json.dumps({'checks':results,'live_tool_coverage_verified':False,'host_settings_modified':False}))
