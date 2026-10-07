#!/usr/bin/env python3
"""No-network cross-agent reuse demonstration; leaves its generated draft for inspection."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_police.ledger import Ledger
from token_police import reuse

home = Path(tempfile.mkdtemp(prefix='agentbrake-demo-'))
ledger = Ledger(home/'ledger.sqlite3')
for i, agent in enumerate(('builder','reviewer','builder')):
    reuse.record(ledger, dict(schema_version=1, event_id=f'demo-{i}', project_id='demo',
        scope_id='client-a', agent_id=agent, task_id=f'task-{i}', operation='secret-names',
        operation_version='1', input_fingerprint=hashlib.sha256(b'demo-revision').hexdigest(),
        status='success', evidence=f'demo-artifact:{i}'))
print(json.dumps({'synthetic':True, 'home':str(home), 'candidates':reuse.scan(ledger,'demo','client-a'),
    'drafts':reuse.draft(ledger,home,'demo','client-a'), 'billing_savings':'unknown'}, indent=2))
ledger.db.close()
