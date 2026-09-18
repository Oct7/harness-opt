import json
import tempfile
import unittest
from pathlib import Path
from harness_opt.report import pick_observed, report as write_class_report

MODELS = [
    {'id': 'grok-4.6', 'efforts': ['low', 'medium', 'high', 'xhigh']},
    {'id': 'composer-2.5-fast', 'efforts': ['low', 'medium']},
]


class PickObservedTests(unittest.TestCase):
    def test_debug_picks_ceiling_model_at_class_cap(self):
        self.assertEqual(
            pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh'),
            {'model': 'grok-4.6', 'effort': 'high'})

    def test_git_is_low_on_ceiling_model_if_allowed(self):
        self.assertEqual(
            pick_observed('git_deploy_ops', MODELS, 'grok-4.6', 'xhigh'),
            {'model': 'grok-4.6', 'effort': 'low'})

    def test_falls_back_to_first_model_that_allows_effort(self):
        only = [{'id': 'composer-2.5-fast', 'efforts': ['low']}]
        self.assertEqual(
            pick_observed('git_deploy_ops', only, 'missing', 'low'),
            {'model': 'composer-2.5-fast', 'effort': 'low'})

    def test_mixed_and_unknown_are_none(self):
        self.assertIsNone(pick_observed('mixed_or_unclear', MODELS, 'grok-4.6', 'xhigh'))

    def test_above_ceiling_effort_not_used(self):
        self.assertEqual(
            pick_observed('architecture_greenfield', MODELS, 'grok-4.6', 'high'),
            {'model': 'grok-4.6', 'effort': 'high'})

    def test_feedback_good_bad(self):
        good = {'model': 'grok-4.6', 'effort': 'medium', 'verdict': 'good'}
        self.assertEqual(pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh', good),
                         {'model': 'grok-4.6', 'effort': 'medium'})
        bad = {'model': 'grok-4.6', 'effort': 'medium', 'verdict': 'bad'}
        self.assertEqual(pick_observed('debug_investigate', MODELS, 'grok-4.6', 'xhigh', bad),
                         {'model': 'grok-4.6', 'effort': 'high'})

    def test_unknown_id_not_invented(self):
        only = [{'id': 'composer-2.5-fast', 'efforts': ['low']}]
        self.assertIsNone(pick_observed('debug_investigate', only, 'nope', 'high'))


class WriteReportTests(unittest.TestCase):
    def test_writes_observed_and_keeps_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            routing = state / 'model-routing' / 'routing.json'
            routing.parent.mkdir(parents=True)
            routing.write_text(json.dumps({
                'schema_version': 2,
                'classes': {'debug_investigate': {
                    'recommended': {'runner': 'codex', 'model': 'sol', 'effort': 'high'},
                    'evidence': [{'run_id': 'x'}],
                    'feedback': [{'verdict': 'good', 'model': 'grok-4.6', 'effort': 'high', 'host': 'cursor'}],
                    'observed': {},
                }},
            }))
            rows = [dict(prompt='로그인 오류 원인 파악', stamp='2026-09-18T00:00:00+00:00',
                         later=[], session='s1', failed=False)]
            result = write_class_report(
                'cursor', state, hosts=('cursor',),
                catalogs={'cursor': [{'id': 'grok-4.6', 'efforts': ['low', 'high', 'xhigh']}]},
                ceilings={'cursor': {'model': 'grok-4.6', 'effort': 'xhigh'}},
                turns=rows)
            data = json.loads(routing.read_text())
            row = data['classes']['debug_investigate']
            self.assertEqual(row['recommended']['model'], 'sol')
            self.assertEqual(row['evidence'][0]['run_id'], 'x')
            self.assertEqual(row['observed']['cursor']['effort'], 'high')
            self.assertTrue((state / 'model-routing' / 'REPORT.md').is_file())
            self.assertEqual(result['status'], 'ok')

    def test_empty_history_is_ok(self):
        with tempfile.TemporaryDirectory() as temp:
            result = write_class_report(
                'codex', Path(temp), hosts=('codex',),
                catalogs={'codex': []}, ceilings={'codex': {'model': 'x', 'effort': 'high'}},
                turns=[])
            self.assertEqual(result['status'], 'ok')
            self.assertIn('empty', result.get('reason', 'empty'))
