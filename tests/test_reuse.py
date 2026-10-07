import hashlib
from pathlib import Path
import tempfile
import unittest
from token_police.ledger import Ledger, Invalid
from token_police import reuse


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.ledger = Ledger(self.home/'ledger.sqlite3')

    def tearDown(self):
        self.ledger.db.close()
        self.temp.cleanup()

    def event(self, number, agent='a', **updates):
        return dict(dict(schema_version=1,event_id=str(number),project_id='p',scope_id='s',
            agent_id=agent,task_id='task',operation='secret-names',operation_version='1',
            input_fingerprint=hashlib.sha256(b'input').hexdigest(),status='success',evidence='artifact:1'), **updates)

    def seed(self):
        for n,agent in enumerate(('a','b','a')):
            reuse.record(self.ledger,self.event(n,agent))

    def test_retries_conflicts_and_distinct_agents(self):
        event = self.event(0)
        self.assertTrue(reuse.record(self.ledger,event)['added'])
        self.assertFalse(reuse.record(self.ledger,event)['added'])
        with self.assertRaises(Invalid):
            reuse.record(self.ledger,self.event(0,'b'))
        for n in (1,2):
            reuse.record(self.ledger,self.event(n))
        self.assertEqual(reuse.scan(self.ledger,'p','s'),[])
        reuse.record(self.ledger,self.event(3,'b'))
        candidate = reuse.scan(self.ledger,'p','s')[0]
        self.assertEqual(candidate['distinct_agents'],2)
        self.assertEqual(candidate['exact_inputs_shared_across_agents'],1)

    def test_scope_failure_and_version_isolation(self):
        for n,updates in enumerate(({}, {'scope_id':'other'}, {'status':'failure'}, {'operation_version':'2'})):
            reuse.record(self.ledger,self.event(n,str(n),**updates))
        self.assertEqual(reuse.scan(self.ledger,'p','s'),[])
        self.assertEqual(reuse.scan(self.ledger,'other','s'),[])

    def test_draft_replay_tamper_and_retirement(self):
        self.seed()
        draft = reuse.draft(self.ledger,self.home,'p','s')[0]
        self.assertEqual(reuse.draft(self.ledger,self.home,'p','s')[0],draft)
        reuse.state(self.ledger,self.home,draft['id'],'approved')
        self.assertEqual(reuse.draft(self.ledger,self.home,'p','s')[0]['state'],'approved')
        (Path(draft['path'])/'scripts/run.py').write_text('modified')
        with self.assertRaises(Invalid):
            reuse.state(self.ledger,self.home,draft['id'],'approved')
        self.assertEqual(reuse.state(self.ledger,self.home,draft['id'],'retired')['state'],'retired')

    def test_unknown_operation_never_becomes_code(self):
        for n in range(3):
            reuse.record(self.ledger,self.event(n,str(n),operation='custom-operation'))
        result = reuse.draft(self.ledger,self.home,'p','s')[0]
        self.assertEqual(result['state'],'needs_reviewed_recipe')
        self.assertEqual(list((self.home/'reuse-drafts').iterdir()),[])

    def test_recovery_verifies_existing_directory(self):
        self.seed()
        draft = reuse.draft(self.ledger,self.home,'p','s')[0]
        self.ledger.db.execute('DELETE FROM reuse_packages')
        self.assertEqual(reuse.draft(self.ledger,self.home,'p','s')[0],draft)
        self.ledger.db.execute('DELETE FROM reuse_packages')
        (Path(draft['path'])/'extra.py').write_text('unreviewed')
        with self.assertRaises(Invalid):
            reuse.draft(self.ledger,self.home,'p','s')
