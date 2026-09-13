import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness_opt.cli import main
from harness_opt.providers import load_providers


class ConfigureTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(['configure', *args])
        return code, output.getvalue()

    def test_secret_roundtrip_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'TEST_PROVIDER_KEY': "key'with-$quotes"}, clear=True):
            path = Path(tmp) / '.env'
            path.write_text('# existing settings\nAPP_NAME=demo\n')
            code, output = self.invoke(['openrouter', '--env-file', str(path), '--api-key-env', 'TEST_PROVIDER_KEY'])
            self.assertEqual(code, 0)
            self.assertNotIn("key'with-$quotes", output)
            self.assertEqual(json.loads(output)['status'], 'configured')
            self.assertFalse(json.loads(output)['connection_verified'])
            self.assertEqual(load_providers(path)['openrouter'].api_key, "key'with-$quotes")
            self.assertIn('APP_NAME=demo', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_key_creates_template_and_preserves_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / '.env'
            code, output = self.invoke(['openrouter', '--env-file', str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)['status'], 'needs_api_key')
            path.write_text(path.read_text().replace("HARNESS_OPENROUTER_API_KEY=''", "HARNESS_OPENROUTER_API_KEY='existing-key'"))
            code, output = self.invoke(['openrouter', '--env-file', str(path)])
            self.assertEqual(json.loads(output)['status'], 'configured')
            self.assertEqual(load_providers(path)['openrouter'].api_key, 'existing-key')

    def test_invalid_input_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / '.env'
            path.write_text('APP_NAME=keep\n')
            for args in [
                ['bad-name'], ['custom', '--base-url', 'https://user:secret@example.com/v1'],
                ['custom', '--base-url', 'http://example.com/v1'],
                ['custom', '--base-url', 'https://example.com/v1\n'],
                ['openrouter', '--api-key-env', 'MISSING_KEY'],
            ]:
                with self.subTest(args=args):
                    code, _ = self.invoke([*args, '--env-file', str(path)])
                    self.assertEqual(code, 1)
                    self.assertEqual(path.read_text(), 'APP_NAME=keep\n')

    def test_interactive_key_requires_a_terminal(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.stdin.isatty', return_value=False):
            path = Path(tmp) / '.env'
            code, _ = self.invoke(['openrouter', '--env-file', str(path), '--prompt-key'])
            self.assertEqual(code, 1)
            self.assertFalse(path.exists())
