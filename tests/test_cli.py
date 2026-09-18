import contextlib
import io
from pathlib import Path
import unittest
from harness_opt.cli import parser, main

class CliTests(unittest.TestCase):
    def test_budget_is_positive_and_finite(self):
        for value in ('nan', 'inf', '0', '-1'):
            argv = ['optimize', '.', '--runner', 'codex', '--execution', 'api', '--time-limit', '60']
            argv += ['--budget-usd', value]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(argv)

    def test_modes_default_to_all(self):
        args = parser().parse_args(['optimize', '.', '--runner', 'claude', '--time-limit', '10'])
        self.assertEqual(args.mode, 'all')

    def test_version_without_litellm(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as exit:
            main(['--version'])
        self.assertEqual(exit.exception.code, 0)
        self.assertIn('0.3.0', out.getvalue())

    def test_repetition_count_validation(self):
        argv = ['optimize', '.', '--runner', 'codex', '--time-limit', '60']
        for value in ('0', '-1', '1.5', 'nan'):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args([*argv, '--repeats', value])
        self.assertEqual(parser().parse_args([*argv, '--repeats', '5']).repeats, 5)

    def test_current_is_default_without_api_budget(self):
        args = parser().parse_args(['optimize', '.', '--runner', 'codex', '--time-limit', '60'])
        self.assertEqual(args.execution, 'current')
        self.assertIsNone(args.budget_usd)

    def test_api_budget_and_current_mode_boundaries(self):
        base = ['optimize', '.', '--runner', 'codex', '--time-limit', '60']
        for flags, message in [(['--execution', 'api'], 'budget-usd'), (['--mode', 'cost'], 'execution api'), (['--budget-usd', '1'], 'execution api')]:
            with self.subTest(flags=flags), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main([*base, *flags]), 1)
                self.assertIn(message, error.getvalue())

    def test_isolate_and_native_home_flags(self):
        isolated = parser().parse_args(['isolate', '--runner', 'codex', '--destination', '/tmp/native-home'])
        self.assertEqual(isolated.command, 'isolate')
        self.assertEqual(isolated.destination, Path('/tmp/native-home'))
        self.assertFalse(isolated.force)
        args = parser().parse_args(['optimize', '.', '--runner', 'codex', '--time-limit', '10', '--native-home', '/tmp/native-home'])
        self.assertEqual(args.native_home, Path('/tmp/native-home'))
        grok = parser().parse_args(['catalog', '--scope', 'global', '--runner', 'grok'])
        self.assertEqual(grok.runner, 'grok')
        classes = parser().parse_args(['catalog', '--scope', 'project', '--runner', 'codex', '--view', 'classes'])
        self.assertEqual(classes.view, 'classes')
        calibrate = parser().parse_args(['calibrate', '--class', 'debug_investigate', '--runner', 'codex', '--time-limit', '10'])
        self.assertEqual(calibrate.command, 'calibrate')
        self.assertEqual(calibrate.task_class, 'debug_investigate')
        self.assertEqual(calibrate.execution, 'current')

    def test_report_command_exists(self):
        args = parser().parse_args(['report', '--runner', 'codex'])
        self.assertEqual(args.command, 'report')
