import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness_opt.runner import WorkspaceSnapshot, capture_profile, execute, _activate, native_usage


class RunnerTests(unittest.TestCase):
    def test_snapshot_same_state_and_no_source_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'input').write_text('original')
            snapshot = WorkspaceSnapshot(source, root / 'snapshot')
            first = snapshot.restore(root / 'first')
            (first / 'input').write_text('changed')
            second = snapshot.restore(root / 'second')
            self.assertEqual((second / 'input').read_text(), 'original')
            self.assertEqual((source / 'input').read_text(), 'original')
            with self.assertRaises(ValueError):
                snapshot.restore(source)
            (source / 'link').symlink_to(root)
            with self.assertRaises(ValueError):
                WorkspaceSnapshot(source, root / 'unsafe')

    def test_native_execution_preserves_configuration_and_redacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / 'home'
            (home / '.claude').mkdir(parents=True)
            (home / '.claude/agents').mkdir()
            (home / '.claude/agents/fixed.md').write_text('---\nname: fixed\nmodel: fixed-subagent\n---\nReview.')
            (home / '.claude/agents/helper.custom').write_text('original helper')
            config = {'model': 'baseline', 'effortLevel': 'high', 'hooks': {'test': 'retained'}}
            (home / '.claude/settings.json').write_text(json.dumps(config))
            source = root / 'source'
            source.mkdir()
            skill = source / 'demo'
            skill.mkdir()
            (skill / 'SKILL.md').write_text('---\nname: demo\n---\nDo work.')
            binary = root / 'claude'
            binary.write_text('#!/usr/bin/env python3\nimport sys,os,json,pathlib\nif "--version" in sys.argv: print("fake 1");sys.exit()\nconfig=json.loads((pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"])/"settings.json").read_text())\nassert config["hooks"]["test"]=="retained"\nassert "model: fixed-subagent" in (pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"])/"agents/fixed.md").read_text()\nassert sys.stdin.read().startswith("/demo\\n")\npathlib.Path("result.txt").write_text("done")\nprint(os.environ["TEST_API_KEY"])\n')
            binary.chmod(0o755)
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'TEST_API_KEY': 'secret-value-123', 'CLAUDE_CONFIG_DIR': str(home / '.claude'), 'CODEX_HOME': str(home / '.codex')}), patch('shutil.which', return_value=str(binary)):
                profile = capture_profile('claude', source)
                self.assertNotIn('retained', json.dumps(profile))
                workspace = WorkspaceSnapshot(source, root / 'snapshot').restore(root / 'run')
                profile['gateway_api_key'] = 'ephemeral-key-xyz'
                result = execute(profile, workspace, 'work', 'http://127.0.0.1:1', 10, source / 'demo')
                self.assertEqual(result['status'], 'completed', result)
                self.assertIn('result.txt', result['artifacts'])
                self.assertNotIn('secret-value-123', result['output'])
                self.assertFalse((source / 'result.txt').exists())
                self.assertEqual(json.loads((home / '.claude/settings.json').read_text()), config)
                with self.assertRaises(ValueError):
                    execute(profile, source, 'work', None, 1)
                helper = home / '.claude/agents/helper.custom'
                helper.write_text('changed helper')
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    execute(profile, workspace, 'work', None, 1)
                helper.write_text('original helper')
                (home / '.claude/agents/new.md').write_text('new agent')
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    execute(profile, workspace, 'work', None, 1)

    def test_plugin_activation_is_native_or_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin = root / 'plugin'
            (plugin / '.claude-plugin').mkdir(parents=True)
            (plugin / '.claude-plugin/plugin.json').write_text('{"name":"demo"}')
            (plugin / 'skills/task').mkdir(parents=True)
            (plugin / 'skills/task/SKILL.md').write_text('---\nname: task\n---\nWork.')
            workspace = root / 'workspace'
            workspace.mkdir()
            args, prompt = _activate('claude', workspace, plugin)
            self.assertEqual(prompt, '/demo:task\n')
            self.assertEqual(args[0], '--plugin-dir')
            self.assertTrue(Path(args[1]).is_relative_to(workspace))
            (plugin / '.codex-plugin').mkdir()
            (plugin / '.codex-plugin/plugin.json').write_text('{"name":"demo"}')
            other_workspace = root / 'codex-workspace'
            other_workspace.mkdir()
            args, prompt = _activate('codex', other_workspace, plugin)
            self.assertEqual(args, [])
            self.assertEqual(prompt, '$task\n')

    def test_workspace_root_skill_staging_and_entrypoint_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'SKILL.md').write_text('---\nname: task\n---\nWork.')
            args, prompt = _activate('codex', root, root, 'SKILL.md')
            installed = root / '.agents/skills/task'
            self.assertTrue((installed / 'SKILL.md').is_file())
            self.assertFalse((installed / '.agents').exists())
            self.assertEqual(prompt, '$task\n')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('one', 'two'):
                (root / 'skills' / name).mkdir(parents=True)
                (root / 'skills' / name / 'SKILL.md').write_text('---\nname: ' + name + '\n---\nWork.')
            args, prompt = _activate('claude', root, root, 'skills/two/SKILL.md')
            self.assertEqual(prompt, '/two\n')

    def test_alternate_subagent_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.codex/agents').mkdir(parents=True)
            (root / '.codex/config.toml').write_text('model="main"\nmodel_reasoning_effort="high"\n')
            (root / '.codex/agents/fixed.toml').write_text('model="fixed"\nmodel_provider="unmetered"\n')
            with patch('pathlib.Path.home', return_value=root), patch.dict(os.environ, {'CODEX_HOME': str(root / '.codex')}):
                with self.assertRaisesRegex(ValueError, 'provider override'):
                    capture_profile('codex', root / 'workspace')

    def test_ancestor_context_requires_wider_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'AGENTS.md').write_text('Required parent context')
            (root / 'child').mkdir()
            with self.assertRaisesRegex(ValueError, 'Ancestor instructions'):
                capture_profile('codex', root / 'child', model='test', effort='high')

    def test_native_usage_totals_do_not_double_count(self):
        claude = {'type': 'result', 'usage': {'input_tokens': 10, 'cache_read_input_tokens': 20,
                  'cache_creation_input_tokens': 5, 'output_tokens': 9,
                  'output_tokens_details': {'thinking_tokens': 3}}, 'total_cost_usd': .2}
        result = native_usage(json.dumps(claude), 'claude')
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['reasoning_tokens']), (35, 9, 3))
        self.assertEqual(result['reported_cost_usd'], .2)
        codex = '\n'.join(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': n, 'output_tokens': 9,
                'cached_input_tokens': 3, 'reasoning_output_tokens': 2}}) for n in (10, 20))
        result = native_usage(codex, 'codex')
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['cached_input_tokens']), (30, 18, 6))
        self.assertIsNone(result['cache_creation_input_tokens'])
        self.assertIsNone(native_usage('not JSON', 'claude')['input_tokens'])
        self.assertIsNone(native_usage(codex + '\n{"type":"turn.failed"}', 'codex')['input_tokens'])
        fallback = {'type': 'result', 'modelUsage': {'fixed': {'inputTokens': 4, 'outputTokens': 3,
                    'cacheReadInputTokens': 2, 'cacheCreationInputTokens': 1}}}
        self.assertEqual(native_usage(json.dumps(fallback), 'claude')['input_tokens'], 7)

    def test_current_defaults_preserve_file_auth_without_model_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / 'home'
            (home / '.codex').mkdir(parents=True)
            auth = home / '.codex/auth.json'
            auth.write_text('{"access_token":"fixture-private-token"}')
            source, workspace = root / 'source', root / 'workspace'
            source.mkdir()
            workspace.mkdir()
            binary = root / 'codex'
            binary.write_text('#!/usr/bin/env python3\nimport sys,os,pathlib,json\nif "--version" in sys.argv: print("fake 1");sys.exit()\nassert "--model" not in sys.argv\nassert os.environ["OPENAI_API_KEY"]=="fixture-existing-api"\nassert os.environ["CLAUDE_CODE_OAUTH_TOKEN"]=="fixture-existing-oauth"\nassert "HARNESS_GATEWAY_TOKEN" not in os.environ\nassert not any("model_reasoning_effort" in arg for arg in sys.argv)\nauth=pathlib.Path(os.environ["CODEX_HOME"])/"auth.json"\nassert json.loads(auth.read_text())["access_token"]=="fixture-private-token"\nauth.write_text("changed isolated copy")\nprint(json.dumps({"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":2}}))\n')
            binary.chmod(0o755)
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'PATH': os.environ['PATH'], 'CODEX_HOME': str(home / '.codex'), 'OPENAI_API_KEY': 'fixture-existing-api', 'CLAUDE_CODE_OAUTH_TOKEN': 'fixture-existing-oauth'}, clear=True), patch('shutil.which', return_value=str(binary)):
                profile = capture_profile('codex', source, current=True)
                self.assertIsNone(profile['model'])
                self.assertIsNone(profile['effort'])
                result = execute(profile, workspace, 'work', None, 10)
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['usage']['input_tokens'], 7)
                self.assertEqual(result['usage_source'], 'native_runner')
                self.assertEqual(json.loads(auth.read_text())['access_token'], 'fixture-private-token')

    def test_pretty_printed_native_auth_error_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home, source, workspace = root / 'home', root / 'source', root / 'workspace'
            for path in (home, source, workspace):
                path.mkdir()
            binary = root / 'claude'
            binary.write_text('#!/usr/bin/env python3\nimport sys,json\nif "--version" in sys.argv: print("fake 1");sys.exit()\nprint(json.dumps({"type":"result","is_error":True,"result":"Not logged in. Please run /login"},indent=2))\n')
            binary.chmod(0o755)
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {'PATH': os.environ['PATH']}, clear=True), patch('shutil.which', return_value=str(binary)):
                profile = capture_profile('claude', source, current=True)
                result = execute(profile, workspace, 'work', None, 10)
                self.assertEqual(result['returncode'], 0)
                self.assertEqual(result['status'], 'authentication_required')
                self.assertIn('keychain', result['authentication_guidance'])
                self.assertIn('No new API key', result['authentication_guidance'])

    def test_missing_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('harness_opt.runner._configuration', return_value=({}, {})), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError):
                    capture_profile('codex', root)


if __name__ == '__main__':
    unittest.main()
