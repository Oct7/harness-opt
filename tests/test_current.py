import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness_opt.optimizer import optimize, run_profile


class CurrentWorkflowTests(unittest.TestCase):
    def experiment(self, with_usage=True, slower=False, mode='steps', fail_auth=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'SKILL.md').write_text('Write answer.txt with correct result.')
            profile = {'runner': 'codex', 'model': 'existing-model', 'effort': 'low',
                       'version': 'fixture', 'workspace': str(source)}
            def execute(active, work, prompt, gateway_url, timeout, target=None):
                self.assertIsNone(gateway_url)
                self.assertNotIn('gateway_api_key', active)
                self.assertEqual(active['model'], 'existing-model')
                changed = False
                if 'Generate independent' in prompt:
                    output = json.dumps({'cases': [dict(kind=kind, prompt='Write the file.', criteria=['Correct file'], required_files=['answer.txt'])
                        for kind in ('normal', 'normal', 'boundary', 'failure')]})
                elif 'Propose ONE' in prompt or 'Combine ALL' in prompt:
                    output = json.dumps({'changes': {'SKILL.md': 'Write answer.txt with correct result. Read once.'}})
                elif 'Evaluate two anonymous' in prompt:
                    output = json.dumps({'verdict': 'equivalent_or_better', 'reason': 'Required artifact matches.'})
                else:
                    skill = Path(target) if Path(target).is_file() else Path(target) / 'SKILL.md'
                    changed = 'Read once' in skill.read_text()
                    if changed and fail_auth:
                        return {'status': 'authentication_required', 'authentication_guidance': 'Native login unavailable.',
                                'output': '', 'duration': 1, 'usage': None}
                    (work / 'answer.txt').write_text('correct')
                    output = 'done'
                return {'status': 'completed', 'output': output, 'duration': (3 if slower else 1) if changed else 2,
                        'usage': {'input_tokens': 80 if changed else 100, 'output_tokens': 20} if with_usage else None,
                        'reported_cost_usd': 99, 'artifacts': {}}
            with patch('harness_opt.optimizer.capture_profile', return_value=profile), \
                 patch('harness_opt.optimizer.execute', side_effect=execute), \
                 patch('harness_opt.optimizer.load_providers', side_effect=AssertionError('Current must not load API settings')), \
                 patch('harness_opt.optimizer.discover_models', side_effect=AssertionError('Current must not query catalogs')), \
                 patch('harness_opt.optimizer.Gateway', side_effect=AssertionError('Current must not start a gateway')):
                report = optimize(source, 'codex', mode, None, 60, root / 'state', None)
                self.assertEqual(report['execution'], 'current')
                self.assertIsNone(report['evaluation_cost_usd'])
                self.assertIsNone(report['budget_remaining_usd'])
                self.assertFalse(report['cost_savings_verified'])
                if fail_auth:
                    self.assertEqual(report['trials'][0]['status'], 'unverified')
                    self.assertEqual(report['trials'][0]['runs'][0]['result']['reason'], 'Native login unavailable.')
                    repeated = optimize(source, 'codex', mode, None, 60, root / 'state', None)
                    self.assertTrue(repeated['cases_reused'])
                    self.assertFalse(repeated['trials'][0]['reused'])
                    return
                if slower:
                    self.assertEqual(report['recommendations'], [])
                    return
                self.assertEqual(report['status'], 'verified_improvement', report['reasons'])
                if mode == 'all':
                    self.assertEqual({trial['name'] for trial in report['trials']},
                                     {'steps', 'structure', 'combined-changes', 'confirm:steps', 'confirm:structure', 'confirm:combined-changes'})
                recommendation = report['recommendations'][0]
                self.assertIsNone(recommendation['cost_usd'])
                self.assertIn('completion_time', recommendation['improvements'])
                self.assertEqual('reported_tokens' in recommendation['improvements'], with_usage)
                self.assertEqual(report['trials'][-1]['mean_total_tokens'], 100 if with_usage else None)
                self.assertFalse((source / 'answer.txt').exists())
                replay = json.loads(Path(recommendation['profile']).read_text())
                self.assertEqual(replay['execution'], 'current')
                result = run_profile(recommendation['profile'], 'Write the file.', None, 30, workspace=source)
                self.assertEqual(result['status'], 'completed')
                self.assertIsNone(result['cost_usd'])
                self.assertTrue((Path(result['workspace']) / 'answer.txt').exists())
                self.assertFalse((source / 'answer.txt').exists())

    def test_current_optimization_and_replay_need_no_provider(self):
        self.experiment(mode='all')

    def test_authentication_failure_is_unverified_and_retried(self):
        self.experiment(fail_auth=True)

    def test_missing_usage_stays_unknown_but_time_can_improve(self):
        self.experiment(with_usage=False)

    def test_lower_tokens_do_not_hide_slower_execution(self):
        self.experiment(slower=True)
