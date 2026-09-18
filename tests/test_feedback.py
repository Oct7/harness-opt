import json
import tempfile
import unittest
from pathlib import Path
from harness_opt.feedback import record_feedback
from harness_opt.report import pick_observed


class FeedbackTests(unittest.TestCase):
    def test_appends_and_skips_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            before = record_feedback(state, 'debug_investigate', 'cursor', 'grok-4.6', 'high', 'good')
            self.assertEqual(before['status'], 'ok')
            data = json.loads((state / 'model-routing' / 'routing.json').read_text())
            self.assertEqual(data['classes']['debug_investigate']['feedback'][-1]['verdict'], 'good')
            raw = (state / 'model-routing' / 'routing.json').read_bytes()
            skipped = record_feedback(state, 'debug_investigate', 'cursor', '', 'high', 'good')
            self.assertEqual(skipped['status'], 'skipped')
            self.assertEqual((state / 'model-routing' / 'routing.json').read_bytes(), raw)

    def test_latest_feedback_changes_next_observed(self):
        models = [{'id': 'grok-4.6', 'efforts': ['low', 'medium', 'high', 'xhigh']}]
        self.assertEqual(
            pick_observed('debug_investigate', models, 'grok-4.6', 'xhigh',
                          {'model': 'grok-4.6', 'effort': 'high', 'verdict': 'bad'}),
            {'model': 'grok-4.6', 'effort': 'xhigh'})
