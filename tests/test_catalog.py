import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness_opt.catalog import catalog
from harness_opt.runner import _native_files


class CatalogTests(unittest.TestCase):
    def test_aliases_are_preserved_and_cycles_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'version').mkdir()
            (root / 'version/config').write_text('required')
            (root / 'latest').symlink_to(root / 'version', target_is_directory=True)
            self.assertEqual({str(p.relative_to(root)) for p in _native_files(root)}, {'version/config', 'latest/config'})
            with tempfile.TemporaryDirectory() as destination:
                copied = Path(destination) / 'native'
                shutil.copytree(root, copied, symlinks=False)
                (copied / 'latest/config').write_text('isolated')
                self.assertEqual((root / 'version/config').read_text(), 'required')
                self.assertEqual((copied / 'version/config').read_text(), 'required')
            (root / 'version/loop').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'cyclic.*loop'):
                list(_native_files(root))

    def test_inventory_usage_and_unknown_history(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            native = home / '.codex'
            for name in ('demo', 'idle', 'harness-opt'):
                path = native / 'skills' / name
                path.mkdir(parents=True)
                (path / 'SKILL.md').write_text(f'---\nname: {name}\n---\nWork.')
            (native / 'skills/alias').symlink_to(native / 'skills/demo', target_is_directory=True)
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'CODEX_HOME': str(native)}):
                result = catalog('global', 'codex', home)
                self.assertEqual(len(result['skills']), 2)
                self.assertEqual(result['suggestions'], [])
                sessions = native / 'sessions'
                sessions.mkdir()
                from datetime import datetime, timezone
                stamp = datetime.now(timezone.utc).isoformat()
                events = [dict(type='event_msg', timestamp=stamp, payload=dict(type='user_message', message='$demo')),
                          dict(type='event_msg', timestamp=stamp, payload=dict(type='user_message', message='$demo')),
                          dict(type='response_item', timestamp=stamp, payload=dict(type='message', role='user', content=[dict(type='input_text', text='$demo')])) ,
                          dict(type='response_item', timestamp=stamp, payload=dict(role='developer', content='$idle'))]
                (sessions / 'session.jsonl').write_text('\n'.join(map(json.dumps, events)) + '\ninvalid')
                result = catalog('global', 'codex', home, 'frequent')
                self.assertEqual([(r['name'], r['count']) for r in result['skills']], [('demo', 1)])
                self.assertEqual(result['coverage']['malformed_or_unreadable'], 1)
                self.assertEqual(catalog('project', 'codex', home)['coverage']['events'], 0)
                self.assertTrue(any(s['action'] == 'review_removal' for s in result['suggestions']))

    def test_claude_plugins_and_project_history(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            project = home / 'project'
            native = home / '.claude'
            plugin = project / 'plugins/demo'
            (plugin / '.claude-plugin').mkdir(parents=True)
            (plugin / '.claude-plugin/plugin.json').write_text('{"name":"demo"}')
            (plugin / 'skills/review').mkdir(parents=True)
            (plugin / 'skills/review/SKILL.md').write_text('---\nname: review\n---')
            history = native / 'projects'
            history.mkdir(parents=True)
            from datetime import datetime, timezone
            event = dict(type='assistant', cwd=str(project), timestamp=datetime.now(timezone.utc).isoformat(),
                         message=dict(content=[dict(type='tool_use', name='Skill', input=dict(skill='demo:review'))]))
            (history / 'log.jsonl').write_text(json.dumps(event))
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(native)}):
                result = catalog('project', 'claude', project, 'recent')
                self.assertEqual(result['skills'][0]['count'], 1)
                self.assertEqual(result['skills'][0]['plugin'], 'demo')
                self.assertFalse(any(s['kind'] == 'plugin' for s in result['suggestions']))

    def test_grok_installed_plugin_and_prompt_history(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            native = home / '.grok'
            plugin = native / 'installed-plugins/demo-hash'
            (plugin / '.claude-plugin').mkdir(parents=True)
            (plugin / '.claude-plugin/plugin.json').write_text('{"name":"demo"}')
            (plugin / 'skills/review').mkdir(parents=True)
            (plugin / 'skills/review/SKILL.md').write_text('---\nname: review\n---')
            (native / 'skills/idle').mkdir(parents=True)
            (native / 'skills/idle/SKILL.md').write_text('---\nname: idle\n---')
            from datetime import datetime, timezone
            from urllib.parse import quote
            stamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            project = home / 'project'
            history = native / 'sessions' / quote(str(project), safe='')
            history.mkdir(parents=True)
            (history / 'prompt_history.jsonl').write_text(
                json.dumps({'prompt': '/demo:review\nFetch the page', 'timestamp': stamp, 'is_bash': False}) + '\n'
                + json.dumps({'prompt': 'ls', 'timestamp': stamp, 'is_bash': True}) + '\n')
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'GROK_HOME': str(native)}):
                result = catalog('global', 'grok', project, 'recent')
                self.assertEqual(result['skills'][0]['name'], 'review')
                self.assertEqual(result['skills'][0]['count'], 1)
                self.assertEqual(result['skills'][0]['plugin'], 'demo')
                self.assertEqual(catalog('project', 'grok', project)['coverage']['events'], 2)

    def test_class_view_is_project_local_and_calibratable(self):
        pad = ' Include reproduction steps, expected files, and the exact error text from the logs.'
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            project = home / 'project'
            project.mkdir()
            native = home / '.codex'
            sessions = native / 'sessions'
            sessions.mkdir(parents=True)
            stamp = datetime.now(timezone.utc).isoformat()
            def session(name, prompts):
                path = sessions / f'{name}.jsonl'
                lines = [json.dumps({'type': 'session_meta', 'timestamp': stamp, 'payload': {'cwd': str(project)}})]
                for prompt in prompts:
                    lines.append(json.dumps({'type': 'response_item', 'timestamp': stamp,
                                             'payload': {'type': 'message', 'role': 'user',
                                                         'content': [{'type': 'input_text', 'text': prompt}]}}))
                path.write_text('\n'.join(lines) + '\n')
            session('n1', ['qwen playground think 누출 원인 분석 /apps/web/playground 에서 사고과정이 본문에 섞이는 오류를 재현해줘.' + pad])
            session('n2', ['카탈로그 준비중 표시 오류 원인 /apps/admin/catalog 의 Flux 모델 상태가 잘못 나오는 문제를 재현해줘.' + pad])
            session('b', ['원인?'])
            session('f', ['로그인 문제 파악 /apps/api 경로에서 세션이 끊기는 오류를 재현하고 원인을 자세히 적어줘.' + pad, '고치 안 됨 실패'])
            session('d', ['푸시 배포해.'])
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'CODEX_HOME': str(native)}):
                with self.assertRaisesRegex(ValueError, 'workspace-local'):
                    catalog('global', 'codex', project, 'classes')
                result = catalog('project', 'codex', project, 'classes')
                self.assertEqual(result['skills'], [])
                names = {row['name']: row for row in result['classes']}
                self.assertEqual(names['debug_investigate']['count'], 4)
                self.assertTrue(names['debug_investigate']['calibratable'])
                self.assertEqual(names['git_deploy_ops']['count'], 1)
                self.assertFalse(names['git_deploy_ops']['calibratable'])
