import unittest
from harness_opt.classify import (
    classify, is_mutating, is_noise, kind_for, criteria_for, select_cases, class_summary,
    effort_cap, load_turns, load_workspace_turns,
)

PAD = ' Include reproduction steps, expected files, and the exact error text from the logs.'


class ClassifyTests(unittest.TestCase):
    def test_noise_and_mutating(self):
        self.assertTrue(is_noise('# AGENTS.md instructions for /tmp'))
        self.assertTrue(is_noise('<environment_context> cwd'))
        self.assertTrue(is_mutating('푸시 배포해.'))
        self.assertTrue(is_mutating('전체 git pull'))
        self.assertEqual(classify('푸시 배포해.'), 'git_deploy_ops')

    def test_class_priority(self):
        self.assertEqual(classify('nightly canary가 red다. 돈잡 3종이 같은 분에 실패.'), 'multi_system_incident')
        self.assertEqual(classify('qwen 플레이그라운드 사고과정 노출. 원인 분석.'), 'debug_investigate')
        self.assertEqual(classify('토큰미터 glassmorphism으로 완전히 개선해.'), 'ui_redesign')
        self.assertEqual(classify('명칭만 채티로 변경해줘.'), 'ui_tweak')
        self.assertEqual(classify('가우시안 메타버스 시스템 아이디어 제안해줘.'), 'architecture_greenfield')
        self.assertEqual(classify('스킬 플러그인 전수 점검해서 리스트 공유.'), 'review_audit')
        self.assertEqual(classify('공식 pricing 페이지를 조사하라.'), 'research_docs')
        self.assertEqual(classify('harness-opt hook이 안 붙어. 고쳐줘.'), 'harness_plugin')
        self.assertEqual(classify('참여율에 따라 급여 자동입력 기능을 추가해줘.'), 'implement_feature')
        self.assertEqual(classify('메일 번역해서 답장란에 입력.'), 'content_oneshot')
        self.assertEqual(classify('asdf'), 'mixed_or_unclear')

    def test_kind_and_criteria(self):
        self.assertEqual(kind_for('원인?', [], False), 'boundary')
        self.assertEqual(kind_for('로그인 문제 파악 /apps/api', ['아직도 실패해'], False), 'failure')
        self.assertEqual(kind_for(
            '긴 디버그 요청입니다 /apps/web 오류 경로를 따라 원인을 찾아주세요. 재현 스텝과 기대 결과를 포함해서 적어 주세요.' + PAD,
            [], False), 'normal')
        self.assertEqual(criteria_for('되도록 팝업이 닫히게 해.')[0], '되도록 팝업이 닫히게 해.')
        self.assertEqual(criteria_for('그냥 해줘.')[0], 'Satisfy the user request as written.')

    def test_select_four_cases_heldout_is_last(self):
        rows = [
            dict(prompt='푸시 배포해.', stamp='2026-09-10T00:00:00+00:00', later=[], session='d', failed=False),
            dict(prompt='원인?', stamp='2026-09-02T00:00:00+00:00', later=[], session='b', failed=False),
            dict(prompt='로그인 문제 파악 /apps/api 경로에서 세션이 끊기는 오류를 재현하고 원인을 자세히 적어줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-03T00:00:00+00:00', later=['고치 안 됨 실패'], session='f', failed=False),
            dict(prompt='qwen playground think 누출 원인 분석 /apps/web/playground 에서 사고과정이 본문에 섞이는 오류를 재현해줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-01T00:00:00+00:00', later=[], session='n1', failed=False),
            dict(prompt='카탈로그 준비중 표시 오류 원인 /apps/admin/catalog 의 Flux 모델 상태가 잘못 나오는 문제를 재현해줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-04T00:00:00+00:00', later=[], session='n2', failed=False),
        ]
        cases = select_cases(rows, 'debug_investigate')
        self.assertEqual(len(cases), 4)
        self.assertEqual(sum(c['kind']=='normal' for c in cases), 2)
        self.assertEqual(cases[-1]['split'], 'heldout')
        self.assertTrue(all(c['id'].startswith('case-') for c in cases))
        with self.assertRaisesRegex(ValueError, 'git_deploy_ops|not calibratable'):
            select_cases(rows, 'git_deploy_ops')
        with self.assertRaisesRegex(ValueError, 'four'):
            select_cases(rows[:3], 'debug_investigate')

    def test_class_summary_counts_sessions(self):
        rows = [
            dict(prompt='원인?', stamp='2026-09-02T00:00:00+00:00', later=[], session='b', failed=False),
            dict(prompt='로그인 문제 파악 /apps/api 경로에서 세션이 끊기는 오류를 재현하고 원인을 자세히 적어줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-03T00:00:00+00:00', later=['실패'], session='f', failed=False),
            dict(prompt='qwen playground think 누출 원인 분석 /apps/web/playground 에서 사고과정이 본문에 섞이는 오류를 재현해줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-01T00:00:00+00:00', later=[], session='n1', failed=False),
            dict(prompt='카탈로그 준비중 표시 오류 원인 /apps/admin/catalog 의 Flux 모델 상태가 잘못 나오는 문제를 재현해줘. Include reproduction steps, expected files, and the exact error text from the logs.', stamp='2026-09-04T00:00:00+00:00', later=[], session='n2', failed=False),
            dict(prompt='푸시 배포해.', stamp='2026-09-05T00:00:00+00:00', later=[], session='d', failed=False),
        ]
        summary = {r['name']: r for r in class_summary(rows)}
        self.assertEqual(summary['debug_investigate']['count'], 4)
        self.assertTrue(summary['debug_investigate']['calibratable'])
        self.assertEqual(summary['git_deploy_ops']['count'], 1)
        self.assertFalse(summary['git_deploy_ops']['calibratable'])


class ClassifyRouteTests(unittest.TestCase):
    def test_effort_caps(self):
        self.assertEqual(effort_cap('git_deploy_ops'), 'low')
        self.assertEqual(effort_cap('content_oneshot'), 'low')
        self.assertEqual(effort_cap('ui_tweak'), 'low')
        self.assertEqual(effort_cap('implement_feature'), 'medium')
        self.assertEqual(effort_cap('harness_plugin'), 'medium')
        self.assertEqual(effort_cap('research_docs'), 'medium')
        self.assertEqual(effort_cap('debug_investigate'), 'high')
        self.assertEqual(effort_cap('ui_redesign'), 'high')
        self.assertEqual(effort_cap('review_audit'), 'high')
        self.assertEqual(effort_cap('architecture_greenfield'), 'xhigh')
        self.assertEqual(effort_cap('multi_system_incident'), 'xhigh')
        self.assertIsNone(effort_cap('mixed_or_unclear'))
        self.assertIsNone(effort_cap('nope'))

    def test_load_turns_all_workspaces(self):
        import json, os, tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest.mock import patch
        stamp = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as temp:
            native = Path(temp) / '.codex'
            sessions = native / 'sessions'
            sessions.mkdir(parents=True)
            other = Path(temp) / 'other'
            mine = Path(temp) / 'mine'
            for cwd, name in ((other, 'a.jsonl'), (mine, 'b.jsonl')):
                (sessions / name).write_text(json.dumps({
                    'type': 'session_meta', 'timestamp': stamp,
                    'payload': {'cwd': str(cwd)},
                }) + '\n' + json.dumps({
                    'type': 'response_item', 'timestamp': stamp,
                    'payload': {'type': 'message', 'role': 'user',
                                'content': [{'type': 'input_text', 'text': '원인?'}]},
                }) + '\n')
            with patch.dict(os.environ, {'CODEX_HOME': str(native)}):
                all_rows, _ = load_turns('codex', days=90, workspace=None)
                one, _ = load_workspace_turns('codex', mine, days=90)
            self.assertEqual(len(all_rows), 2)
            self.assertEqual(len(one), 1)
