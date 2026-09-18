import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from harness_opt.hooks import install_hooks
from harness_opt.report import is_stale


class StaleTests(unittest.TestCase):
    def test_fingerprint_and_age(self):
        fresh = {'catalog_cutoff': datetime.now(timezone.utc).date().isoformat(),
                 'catalog_fingerprint': {'cursor': 'aaa'}}
        self.assertFalse(is_stale(fresh, {'cursor': 'aaa'}))
        self.assertTrue(is_stale(fresh, {'cursor': 'bbb'}))
        old = {'catalog_cutoff': (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat(),
               'catalog_fingerprint': {'cursor': 'aaa'}}
        self.assertTrue(is_stale(old, {'cursor': 'aaa'}))


class HookInstallTests(unittest.TestCase):
    def test_keeps_foreign_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'hooks.json'
            path.write_text(json.dumps({
                'version': 1,
                'hooks': {'beforeSubmitPrompt': [{'command': 'other'}],
                          'sessionEnd': [{'command': 'keep-me'}]},
            }))
            install_hooks(path)
            data = json.loads(path.read_text())
            starts = [x['command'] for x in data['hooks']['beforeSubmitPrompt']]
            ends = [x['command'] for x in data['hooks']['sessionEnd']]
            self.assertIn('other', starts)
            self.assertTrue(any('route --host cursor' in c for c in starts))
            self.assertIn('keep-me', ends)
            self.assertTrue(any('feedback --host cursor' in c for c in ends))
            install_hooks(path)
            data = json.loads(path.read_text())
            self.assertEqual(sum('route --host cursor' in x['command'] for x in data['hooks']['beforeSubmitPrompt']), 1)
            self.assertEqual([x['command'] for x in data['hooks']['beforeSubmitPrompt'] if x['command'] == 'other'], ['other'])

    def test_nested_keeps_foreign_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            path.write_text(json.dumps({
                'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'keep'}],
                                                'matcher': ''}]},
                'language': 'korean',
            }))
            install_hooks(Path(temp) / 'cursor.json', claude_settings=path)
            data = json.loads(path.read_text())
            self.assertEqual(data['language'], 'korean')
            commands = [item['command'] for group in data['hooks']['UserPromptSubmit']
                        for item in group.get('hooks') or []]
            self.assertIn('keep', commands)
            self.assertTrue(any('route --host claude' in item for item in commands))
            install_hooks(Path(temp) / 'cursor.json', claude_settings=path)
            again = [item['command'] for group in json.loads(path.read_text())['hooks']['UserPromptSubmit']
                     for item in group.get('hooks') or []]
            self.assertEqual(sum('route --host claude' in item for item in again), 1)

    def test_grok_writes_owned_file(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'hooks'
            directory.mkdir()
            (directory / 'tokenmeter.json').write_text('{"keep": true}\n')
            install_hooks(Path(temp) / 'cursor.json', grok_hooks=directory)
            data = json.loads((directory / 'harness-opt.json').read_text())
            self.assertTrue((directory / 'tokenmeter.json').is_file())
            commands = [item['command'] for group in data['hooks']['UserPromptSubmit']
                        for item in group['hooks']]
            self.assertTrue(any('route --host grok' in item for item in commands))
