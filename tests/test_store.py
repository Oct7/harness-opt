import tempfile
import unittest
from pathlib import Path
from harness_opt.store import Store, fingerprint

class StoreTests(unittest.TestCase):
    def test_only_quality_failures_reused(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'history.sqlite')
            s.put('failure','a',{'status':'authentication_failure'})
            self.assertIsNone(s.failure('a'))
            s.put('failure','a',{'status':'quality_failure'})
            self.assertEqual(s.failure('a')['status'],'quality_failure')
            s.db.execute('UPDATE records SET created=0')
            s.db.commit()
            self.assertIsNone(s.failure('a'))
            self.assertIsNotNone(s.failure('a',versioned=True))
            s.close()
    def test_stable_fingerprint(self):
        self.assertEqual(fingerprint({'a':1,'b':2}),fingerprint({'b':2,'a':1}))
