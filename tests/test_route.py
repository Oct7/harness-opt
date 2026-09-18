import json
import tempfile
import unittest
from pathlib import Path
from harness_opt.route import route


class RouteTests(unittest.TestCase):
    def fixture(self, row):
        state = Path(tempfile.mkdtemp())
        path = state / 'model-routing' / 'routing.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema_version': 2, 'classes': {'debug_investigate': row}}))
        return state

    def test_asks_when_current_above_observed(self):
        state = self.fixture({'observed': {'cursor': {'model': 'grok-4.6', 'effort': 'high'}}})
        result = route('로그인 오류 원인', 'cursor', 'grok-4.6', 'xhigh', '/ws', state)
        self.assertTrue(result['ask'])
        self.assertIn('바꿀까요?', result['message'])
        self.assertIn('unverified', result['message'])
        self.assertEqual(result['source'], 'observed')
        self.assertTrue((state / 'model-routing' / 'outcomes.jsonl').is_file())

    def test_silence_when_at_or_below(self):
        state = self.fixture({'observed': {'cursor': {'model': 'grok-4.6', 'effort': 'high'}}})
        result = route('로그인 오류 원인', 'cursor', 'grok-4.6', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['message'], '')

    def test_prefers_workspace_override(self):
        state = self.fixture({
            'observed': {'codex': {'model': 'sol', 'effort': 'high'}},
            'recommended': {'runner': 'codex', 'model': 'sol', 'effort': 'high'},
            'workspace_overrides': {str(Path('/ws').resolve()): {'runner': 'codex', 'model': 'luna', 'effort': 'low'}},
        })
        result = route('로그인 오류 원인', 'codex', 'sol', 'ultra', '/ws', state)
        self.assertEqual(result['recommended']['model'], 'luna')
        self.assertEqual(result['source'], 'override')

    def test_mixed_is_silent(self):
        state = self.fixture({})
        result = route('asdf', 'codex', 'sol', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['source'], 'none')

    def test_missing_routing_is_silent_exit_shape(self):
        state = Path(tempfile.mkdtemp())
        result = route('로그인 오류 원인', 'codex', 'sol', 'high', '/ws', state)
        self.assertFalse(result['ask'])
        self.assertEqual(result['source'], 'none')
