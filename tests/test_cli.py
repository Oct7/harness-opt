import contextlib
import io
import unittest
from harness_opt.cli import parser, main

class CliTests(unittest.TestCase):
    def test_budget_required_and_finite(self):
        for value in (None, 'nan', 'inf', '0', '-1'):
            argv = ['optimize', '.', '--runner', 'codex', '--time-limit', '60']
            if value is not None:
                argv += ['--budget-usd', value]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(argv)

    def test_modes_default_to_all(self):
        args = parser().parse_args(['optimize', '.', '--runner', 'claude', '--budget-usd', '1', '--time-limit', '10'])
        self.assertEqual(args.mode, 'all')

    def test_version_without_litellm(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as exit:
            main(['--version'])
        self.assertEqual(exit.exception.code, 0)
        self.assertIn('0.1.0', out.getvalue())
