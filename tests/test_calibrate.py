import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from harness_opt.calibrate import calibrate, candidate_pairs, read_routing, write_routing
from harness_opt.cli import main


PAD = ' Include reproduction steps, expected files, and the exact error text from the logs.'
STAMP = datetime.now(timezone.utc).isoformat()


def write_sessions(sessions_dir, project, extra=None):
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rows = {
        'n1': ['qwen playground think 누출 원인 분석 /apps/web/playground 에서 사고과정이 본문에 섞이는 오류를 재현해줘.' + PAD],
        'n2': ['카탈로그 준비중 표시 오류 원인 /apps/admin/catalog 의 Flux 모델 상태가 잘못 나오는 문제를 재현해줘.' + PAD],
        'b': ['원인?'],
        'f': ['로그인 문제 파악 /apps/api 경로에서 세션이 끊기는 오류를 재현하고 원인을 자세히 적어줘.' + PAD, '고치 안 됨 실패'],
        'd': ['푸시 배포해.'],
    }
    if extra is not None:
        rows = extra
    for name, prompts in rows.items():
        lines = [json.dumps({'type': 'session_meta', 'timestamp': STAMP, 'payload': {'cwd': str(project)}})]
        for prompt in prompts:
            lines.append(json.dumps({'type': 'response_item', 'timestamp': STAMP,
                                     'payload': {'type': 'message', 'role': 'user',
                                                 'content': [{'type': 'input_text', 'text': prompt}]}}))
        (sessions_dir / f'{name}.jsonl').write_text('\n'.join(lines) + '\n')


class CandidatePairTests(unittest.TestCase):
    def test_grok_current_uses_captured_effort_only(self):
        listed = [
            {'id': 'grok-ceiling', 'provider': 'native', 'efforts': ['xhigh', 'low']},
            {'id': 'grok-fast', 'provider': 'native', 'efforts': ['xhigh']},
            {'id': 'grok-skip', 'provider': 'native', 'efforts': ['low']},
        ]
        with patch('harness_opt.calibrate.native_models', return_value=listed):
            pairs = candidate_pairs('grok', 'current', {'effort': 'xhigh', 'model': 'grok-ceiling'},
                                    [], 'grok-ceiling', 'xhigh')
        self.assertEqual([(m['id'], effort) for m, effort in pairs], [('grok-fast', 'xhigh')])

    def test_claude_current_effort_only_or_error(self):
        profile = {'efforts': ['low', 'high'], 'model': 'claude-sonnet'}
        pairs = candidate_pairs('claude', 'current', profile, [], 'claude-sonnet', 'high')
        self.assertEqual([effort for _, effort in pairs], ['low'])
        with self.assertRaisesRegex(ValueError, 'no candidate below ceiling'):
            candidate_pairs('codex', 'current', {'efforts': ['high']}, [], 'gpt', 'high')

    def test_api_drops_unknown_prices_and_above_ceiling(self):
        models = [
            {'id': 'base', 'provider': 'fake', 'input_per_million': 2, 'output_per_million': 2,
             'context_window': 100, 'efforts': ['low', 'high', 'ultra']},
            {'id': 'cheap', 'provider': 'fake', 'input_per_million': 1, 'output_per_million': 1,
             'context_window': 100, 'efforts': ['low', 'high', 'ultra']},
            {'id': 'ghost', 'provider': 'fake', 'input_per_million': None, 'output_per_million': 1,
             'context_window': 100, 'efforts': ['high']},
        ]
        pairs = candidate_pairs('codex', 'api', {}, models, 'base', 'high')
        self.assertEqual(sorted((m['id'], effort) for m, effort in pairs),
                         [('base', 'low'), ('cheap', 'high'), ('cheap', 'low')])

    def test_current_uses_full_catalog_below_ceiling(self):
        catalog = [
            {'id': 'ceiling', 'provider': 'native', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'other', 'provider': 'native', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'skip', 'provider': 'native', 'efforts': ['xhigh']},
        ]
        profile = {'effort': 'high', 'model': 'ceiling', 'catalog': catalog}
        with patch('harness_opt.calibrate.native_models', return_value=catalog):
            pairs = candidate_pairs('claude', 'current', profile, [], 'ceiling', 'high')
        self.assertEqual(sorted((m['id'], effort) for m, effort in pairs),
                         [('ceiling', 'low'), ('other', 'high'), ('other', 'low')])


class RoutingTests(unittest.TestCase):
    def test_recommended_updates_only_when_new_winner_beats(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            first = {'runner': 'codex', 'model': 'a', 'effort': 'low'}
            second = {'runner': 'codex', 'model': 'b', 'effort': 'low'}
            write_routing(state, 'debug_investigate', '/ws', first,
                          {'runner': 'codex', 'model': 'a', 'effort': 'high'},
                          {'winner': first, 'improvements': ['completion_time'], 'mean_duration': 2, 'mean_cost_usd': 0.2})
            write_routing(state, 'debug_investigate', '/ws', second,
                          {'runner': 'codex', 'model': 'a', 'effort': 'high'},
                          {'winner': second, 'improvements': ['completion_time'], 'mean_duration': 3, 'mean_cost_usd': 0.3})
            data = read_routing(state)
            self.assertEqual(data['classes']['debug_investigate']['recommended'], first)
            write_routing(state, 'debug_investigate', '/ws', second,
                          {'runner': 'codex', 'model': 'a', 'effort': 'high'},
                          {'winner': second, 'improvements': ['completion_time'], 'mean_duration': 1, 'mean_cost_usd': 0.1})
            data = read_routing(state)
            self.assertEqual(data['classes']['debug_investigate']['recommended'], second)

    def test_write_routing_keeps_observed_and_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            path = state / 'model-routing' / 'routing.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 2, "classes": {"debug_investigate": {'
                            '"observed": {"cursor": {"model": "grok-4.6", "effort": "high"}},'
                            '"feedback": [{"verdict": "ok"}], "evidence": []}}}')
            write_routing(state, 'debug_investigate', '/ws',
                          {'runner': 'codex', 'model': 'a', 'effort': 'low'},
                          {'runner': 'codex', 'model': 'a', 'effort': 'high'},
                          {'winner': {'runner': 'codex', 'model': 'a', 'effort': 'low'},
                           'improvements': ['completion_time'], 'mean_duration': 1})
            data = json.loads(path.read_text())
            row = data['classes']['debug_investigate']
            self.assertEqual(row['observed']['cursor']['model'], 'grok-4.6')
            self.assertEqual(row['feedback'][0]['verdict'], 'ok')
            self.assertGreaterEqual(data['schema_version'], 2)


class CalibrateTests(unittest.TestCase):
    def fixture(self, missing=None):
        root = Path(tempfile.mkdtemp())
        work = root / 'source'
        work.mkdir()
        native = root / '.codex'
        extra = None
        if missing == 'cases':
            extra = {
                'n1': ['qwen playground think 누출 원인 분석 /apps/web/playground 에서 사고과정이 본문에 섞이는 오류를 재현해줘.' + PAD],
                'n2': ['카탈로그 준비중 표시 오류 원인 /apps/admin/catalog 의 Flux 모델 상태가 잘못 나오는 문제를 재현해줘.' + PAD],
                'b': ['원인?'],
            }
        write_sessions(native / 'sessions', work, extra)
        return root, work, native

    def test_cursor_and_blocked_class_and_short_history(self):
        with self.assertRaisesRegex(ValueError, 'cursor'):
            calibrate('debug_investigate', 'cursor', None, 10, Path('/tmp/state'), None)
        with self.assertRaisesRegex(ValueError, 'not calibratable'):
            calibrate('git_deploy_ops', 'codex', None, 10, Path('/tmp/state'), None)
        root, work, native = self.fixture(missing='cases')
        with patch.dict(os.environ, {'CODEX_HOME': str(native)}):
            with self.assertRaisesRegex(ValueError, 'four assignable cases'):
                calibrate('debug_investigate', 'codex', None, 10, root / 'state', None, workspace=work)

    def test_hooks_without_native_home_exit(self):
        root, work, native = self.fixture()
        profile = {'runner': 'codex', 'model': 'base', 'effort': 'high', 'version': 't',
                   'workspace': str(work), 'requires_external_fixture': True, 'external_isolation_verified': False}
        with patch.dict(os.environ, {'CODEX_HOME': str(native)}), \
             patch('harness_opt.calibrate.capture_profile', return_value=profile):
            with self.assertRaisesRegex(ValueError, 'isolate'):
                calibrate('debug_investigate', 'codex', None, 10, root / 'state', None, workspace=work)

    def test_codex_current_without_lower_effort_errors(self):
        root, work, native = self.fixture()
        profile = {'runner': 'codex', 'model': 'base', 'effort': 'high', 'version': 't',
                   'workspace': str(work), 'requires_external_fixture': False, 'external_isolation_verified': True}
        with patch.dict(os.environ, {'CODEX_HOME': str(native)}), \
             patch('harness_opt.calibrate.capture_profile', return_value=profile):
            with self.assertRaisesRegex(ValueError, 'no candidate below ceiling'):
                calibrate('debug_investigate', 'codex', None, 10, root / 'state', None, workspace=work)

    def experiment(self, repeats=3, budget_usd=10, cheap_cost=0.01, seed_routing=None):
        root, work, native = self.fixture()
        state = root / 'state'
        if seed_routing:
            path = state / 'model-routing' / 'routing.json'
            path.parent.mkdir(parents=True)
            path.write_text(seed_routing)
            before = path.read_bytes()
        else:
            before = None
        profile = {'runner': 'codex', 'model': 'base', 'effort': 'high', 'version': 't',
                   'workspace': str(work), 'requires_external_fixture': False, 'external_isolation_verified': True}
        models = [
            {'provider': 'fake', 'id': 'base', 'input_per_million': 2, 'output_per_million': 2,
             'context_window': 100, 'efforts': ['low', 'high', 'ultra']},
            {'provider': 'fake', 'id': 'cheap', 'input_per_million': 1, 'output_per_million': 1,
             'context_window': 100, 'efforts': ['low', 'high', 'ultra']},
            {'provider': 'fake', 'id': 'ghost', 'input_per_million': None, 'output_per_million': 1,
             'context_window': 100, 'efforts': ['high']},
        ]
        provider = SimpleNamespace(api_key='secret-fixture')
        active = {}

        class FakeGateway:
            def __init__(self, provider, model, budget, effort=None):
                self.budget = budget
                self.model = model
                self.api_key = 'temporary'
                self.base_url = 'fake'
                self.compatibility_errors = []
                self.records = []
                self.cost = 0

            def __enter__(self):
                self.reservation = self.budget.reserve(0.02 if self.model['id'] == 'base' else cheap_cost)
                active['gateway'] = self
                return self

            def __exit__(self, *args):
                self.budget.settle(self.reservation, self.cost)

        def fake_execute(profile, workspace, prompt, gateway_url, timeout, target=None):
            g = active['gateway']
            g.cost = 0.02 if profile['model'] == 'base' else cheap_cost
            g.records = [{'cost': g.cost}]
            if 'Evaluate two anonymous' in prompt:
                output = '{"verdict":"equivalent_or_better","reason":"same required result"}'
            else:
                output = 'done'
            return {'status': 'completed', 'output': output,
                    'duration': 2 if profile['model'] == 'base' else 1, 'artifacts': {}}

        with patch.dict(os.environ, {'CODEX_HOME': str(native)}), \
             patch('harness_opt.calibrate.capture_profile', return_value=profile), \
             patch('harness_opt.calibrate.load_providers', return_value={'fake': provider}), \
             patch('harness_opt.calibrate.discover_models', return_value=models), \
             patch('harness_opt.calibrate.Gateway', FakeGateway), \
             patch('harness_opt.calibrate.execute', side_effect=fake_execute):
            report = calibrate('debug_investigate', 'codex', budget_usd, 60, state, None,
                               workspace=work, baseline_provider='fake', repeats=repeats, execution='api')
        names = [trial['name'] for trial in report['trials']]
        self.assertFalse(any('ultra' in name or 'ghost' in name for name in names))
        routing = state / 'model-routing' / 'routing.json'
        return report, routing, before

    def test_verified_winner_writes_override_and_recommended(self):
        report, routing, _ = self.experiment()
        self.assertEqual(report['status'], 'verified_improvement', report['reasons'])
        data = json.loads(routing.read_text())
        row = data['classes']['debug_investigate']
        self.assertEqual(row['recommended']['model'], 'cheap')
        self.assertTrue(row['workspace_overrides'])
        self.assertIn('cursor', row['evidence'][-1]['unverified_for'])
        self.assertEqual(routing.stat().st_mode & 0o777, 0o600)

    def test_provisional_leaves_routing_unchanged(self):
        seed = '{"schema_version":1,"classes":{}}'
        report, routing, before = self.experiment(repeats=1, seed_routing=seed)
        self.assertEqual(report['status'], 'provisional_improvement', report['reasons'])
        self.assertEqual(routing.read_bytes(), before)

    def test_budget_stop_leaves_routing_unchanged(self):
        seed = '{"schema_version":1,"classes":{}}'
        report, routing, before = self.experiment(budget_usd=0.001, seed_routing=seed)
        self.assertEqual(report['status'], 'budget_stopped')
        self.assertEqual(routing.read_bytes(), before)


class CalibrateCliTests(unittest.TestCase):
    def test_cursor_rejected_by_cli(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['calibrate', '--class', 'debug_investigate',
                                   '--runner', 'cursor', '--time-limit', '10']), 1)
            self.assertIn('cursor', err.getvalue())

    def test_mode_flag_rejected(self):
        import contextlib
        import io
        from harness_opt.cli import parser
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(['calibrate', '--class', 'debug_investigate',
                                 '--runner', 'codex', '--time-limit', '10', '--mode', 'all'])
