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

    def test_each_native_call_gets_full_time_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'SKILL.md').write_text('Write answer.txt with correct result.')
            timeouts = []
            clock = [1000.0]
            profile = {'runner': 'codex', 'model': 'existing-model', 'effort': 'low',
                       'version': 'fixture', 'workspace': str(source)}
            def execute(active, work, prompt, gateway_url, timeout, target=None):
                timeouts.append(timeout)
                clock[0] += 100
                if 'Generate independent' in prompt:
                    output = json.dumps({'cases': [dict(kind=kind, prompt='Write the file.', criteria=['Correct file'], required_files=['answer.txt'])
                        for kind in ('normal', 'normal', 'boundary', 'failure')]})
                elif 'Propose ONE' in prompt or 'Combine ALL' in prompt:
                    output = json.dumps({'changes': {'SKILL.md': 'Write answer.txt with correct result. Read once.'}})
                elif 'Evaluate two anonymous' in prompt:
                    output = json.dumps({'verdict': 'equivalent_or_better', 'reason': 'Required artifact matches.'})
                else:
                    (work / 'answer.txt').write_text('correct')
                    output = 'done'
                return {'status': 'completed', 'output': output, 'duration': 1,
                        'usage': {'input_tokens': 10, 'output_tokens': 2}, 'artifacts': {}}
            with patch('harness_opt.budget.time.monotonic', side_effect=lambda: clock[0]), \
                 patch('harness_opt.optimizer.time.monotonic', side_effect=lambda: clock[0]), \
                 patch('harness_opt.optimizer.capture_profile', return_value=profile), \
                 patch('harness_opt.optimizer.execute', side_effect=execute), \
                 patch('harness_opt.optimizer.load_providers', side_effect=AssertionError), \
                 patch('harness_opt.optimizer.Gateway', side_effect=AssertionError):
                optimize(source, 'codex', 'steps', None, 30, root / 'state', None, repeats=1)
            self.assertGreater(len(timeouts), 1)
            self.assertTrue(all(t == 30 for t in timeouts), timeouts)

    def test_current_speed_requires_grok(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            source.mkdir()
            (source / 'SKILL.md').write_text('Work.')
            with self.assertRaisesRegex(ValueError, 'implemented for grok'):
                optimize(source, 'codex', 'speed', None, 60, Path(temp) / 'state', None)

    def test_grok_current_compares_native_models_without_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'SKILL.md').write_text('Write answer.txt with correct result.')
            seen = []
            profile = {'runner': 'grok', 'model': 'grok-4.6', 'effort': 'high',
                       'version': 'fixture', 'workspace': str(source)}
            def execute(active, work, prompt, gateway_url, timeout, target=None):
                self.assertIsNone(gateway_url)
                seen.append(active.get('model'))
                if 'Generate independent' in prompt:
                    output = json.dumps({'cases': [dict(kind=kind, prompt='Write the file.', criteria=['Correct file'], required_files=['answer.txt'])
                        for kind in ('normal', 'normal', 'boundary', 'failure')]})
                elif 'Evaluate two anonymous' in prompt:
                    output = json.dumps({'verdict': 'equivalent_or_better', 'reason': 'Required artifact matches.'})
                else:
                    (work / 'answer.txt').write_text('correct')
                    output = 'done'
                faster = active.get('model') == 'grok-4.5'
                return {'status': 'completed', 'output': output, 'duration': 1 if faster else 2,
                        'usage': {'input_tokens': 50 if faster else 100, 'output_tokens': 10}, 'artifacts': {}}
            with patch('harness_opt.optimizer.capture_profile', return_value=profile), \
                 patch('harness_opt.optimizer.execute', side_effect=execute), \
                 patch('harness_opt.optimizer.native_models', return_value=[
                     {'id': 'grok-4.6', 'provider': 'native', 'efforts': ['high']},
                     {'id': 'grok-4.5', 'provider': 'native', 'efforts': ['high']}]), \
                 patch('harness_opt.optimizer.load_providers', side_effect=AssertionError('Current must not load API settings')), \
                 patch('harness_opt.optimizer.Gateway', side_effect=AssertionError('Current must not start a gateway')):
                report = optimize(source, 'grok', 'speed', None, 60, root / 'state', None, repeats=3)
            self.assertIn('grok-4.5', seen)
            self.assertEqual(report['status'], 'verified_improvement', report['reasons'])
            self.assertTrue(any('grok-4.5' in rec['name'] for rec in report['recommendations']))
            replay = json.loads(Path(report['recommendations'][0]['profile']).read_text())
            self.assertEqual(replay['runner_profile']['model'], 'grok-4.5')

    def test_unsupported_captured_effort_is_omitted_for_other_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'SKILL.md').write_text('Write answer.txt with correct result.')
            efforts = []
            profile = {'runner': 'grok', 'model': 'grok-4.6', 'effort': 'xhigh',
                       'version': 'fixture', 'workspace': str(source)}
            def execute(active, work, prompt, gateway_url, timeout, target=None):
                if 'Write the file' in prompt or prompt == 'Write the file.':
                    efforts.append((active.get('model'), active.get('effort')))
                if 'Generate independent' in prompt:
                    output = json.dumps({'cases': [dict(kind=kind, prompt='Write the file.', criteria=['Correct file'], required_files=['answer.txt'])
                        for kind in ('normal', 'normal', 'boundary', 'failure')]})
                elif 'Evaluate two anonymous' in prompt:
                    output = json.dumps({'verdict': 'equivalent_or_better', 'reason': 'ok'})
                else:
                    (work / 'answer.txt').write_text('correct')
                    output = 'done'
                return {'status': 'completed', 'output': output, 'duration': 1,
                        'usage': {'input_tokens': 10, 'output_tokens': 2}, 'artifacts': {}}
            with patch('harness_opt.optimizer.capture_profile', return_value=profile), \
                 patch('harness_opt.optimizer.execute', side_effect=execute), \
                 patch('harness_opt.optimizer.native_models', return_value=[
                     {'id': 'grok-4.6', 'provider': 'native', 'efforts': ['xhigh']},
                     {'id': 'grok-4.5', 'provider': 'native', 'efforts': ['']}]), \
                 patch('harness_opt.optimizer.load_providers', side_effect=AssertionError), \
                 patch('harness_opt.optimizer.Gateway', side_effect=AssertionError):
                optimize(source, 'grok', 'speed', None, 30, root / 'state', None, repeats=1)
            self.assertIn(('grok-4.5', ''), efforts)
