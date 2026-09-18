"""Public command line; imports expensive runtime dependencies only on execution."""
import argparse
import json
import math
from pathlib import Path
import sys

from . import __version__


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be an integer of at least 1')
    return number


def parser():
    root = argparse.ArgumentParser(prog='harness-opt', description=__doc__)
    root.add_argument('--version', action='version', version=f'harness-opt {__version__}')
    commands = root.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure', help='Create provider settings without making API calls')
    setup.add_argument('provider')
    setup.add_argument('--env-file', type=Path, default=Path('.env'))
    setup.add_argument('--base-url')
    key_source = setup.add_mutually_exclusive_group()
    key_source.add_argument('--api-key-env', help='Read the API key from this environment variable')
    key_source.add_argument('--prompt-key', action='store_true', help='Prompt in a local terminal with hidden input')
    models = commands.add_parser('models', help='Discover configured provider models and prices')
    models.add_argument('--env-file', type=Path, default=Path('.env'))
    models.add_argument('--openrouter', action='store_true', help='Read the public OpenRouter price catalog without credentials')
    inventory = commands.add_parser('catalog', help='List local skills and usage-based review suggestions')
    inventory.add_argument('--scope', choices=['global', 'project'], required=True)
    inventory.add_argument('--runner', choices=['claude', 'codex', 'grok'], required=True)
    inventory.add_argument('--workspace', type=Path, default=Path.cwd())
    inventory.add_argument('--view', choices=['all', 'frequent', 'recent', 'classes'], default='all')
    inventory.add_argument('--days', type=positive_integer, default=90)
    isolated = commands.add_parser('isolate', help='Create an approved native HOME fixture without live hooks/MCP')
    isolated.add_argument('--runner', choices=['claude', 'codex', 'grok'], required=True)
    isolated.add_argument('--destination', type=Path,
                          help='Fake HOME directory (default: ~/.cache/harness-opt/native-home/<runner>)')
    isolated.add_argument('--force', action='store_true', help='Replace an existing destination')
    opt = commands.add_parser('optimize', help='Generate cases, measure, compare, and report')
    opt.add_argument('target', type=Path)
    opt.add_argument('--runner', choices=['claude', 'codex', 'grok'], required=True)
    opt.add_argument('--execution', choices=['current', 'api'], default='current',
                     help='Current native login/model (default), or separately metered API experiments')
    opt.add_argument('--mode', choices=['all', 'steps', 'speed', 'cost', 'structure'], default='all')
    opt.add_argument('--budget-usd', type=positive, help='Required only for --execution api')
    opt.add_argument('--time-limit', type=positive, required=True, help='Wall-clock seconds per native invocation')
    opt.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    opt.add_argument('--env-file', type=Path, default=Path('.env'))
    opt.add_argument('--workspace', type=Path, help='Source workspace (defaults to target directory)')
    opt.add_argument('--baseline-model')
    opt.add_argument('--baseline-provider')
    opt.add_argument('--effort')
    opt.add_argument('--cases', type=int, default=4)
    opt.add_argument('--repeats', type=positive_integer, default=3,
                     help='Final executions per candidate per case (recommended: 3; fewer are provisional)')
    opt.add_argument('--force', action='store_true')
    opt.add_argument('--resume', help='Resume a compatible run; API budgets include prior spend')
    opt.add_argument('--native-home', type=Path, help='Approved isolated native HOME from harness-opt isolate')
    report = commands.add_parser('report', help='Read a saved optimize report or write a class-route report')
    report.add_argument('run_id', nargs='?')
    report.add_argument('--runner', choices=['claude', 'codex', 'grok', 'cursor'])
    report.add_argument('--days', type=positive_integer, default=90)
    report.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    report.add_argument('--format', choices=['json', 'markdown'], default='markdown')
    run = commands.add_parser('run', help='Execute a verified profile in an isolated workspace')
    run.add_argument('profile', type=Path)
    run.add_argument('task')
    run.add_argument('--budget-usd', type=positive, help='Required for API profiles; omitted for current-environment profiles')
    run.add_argument('--time-limit', type=positive, required=True)
    run.add_argument('--env-file', type=Path, default=Path('.env'))
    run.add_argument('--workspace', type=Path, default=Path.cwd())
    route_cmd = commands.add_parser('route', help='Recommend model/effort for a prompt without changing it')
    route_cmd.add_argument('prompt', nargs='?')
    route_cmd.add_argument('--host', choices=['claude', 'codex', 'grok', 'cursor'], required=True)
    route_cmd.add_argument('--model')
    route_cmd.add_argument('--effort')
    route_cmd.add_argument('--workspace', type=Path, default=Path.cwd())
    route_cmd.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    route_cmd.add_argument('--hook-stdin', action='store_true')
    route_cmd.add_argument('--hook-event', default='beforeSubmitPrompt')
    fb = commands.add_parser('feedback', help='Record whether the used model/effort was enough')
    fb.add_argument('--class', dest='task_class')
    fb.add_argument('--host', choices=['claude', 'codex', 'grok', 'cursor'])
    fb.add_argument('--model')
    fb.add_argument('--effort')
    fb.add_argument('--verdict', choices=['good', 'bad'])
    fb.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    fb.add_argument('--hook-stdin', action='store_true')
    hook = commands.add_parser('hook', help='Install or refresh harness-opt model-routing hooks')
    hook_cmds = hook.add_subparsers(dest='hook_command', required=True)
    installed = hook_cmds.add_parser('install')
    installed.add_argument('--cursor-hooks', type=Path, default=Path.home() / '.cursor' / 'hooks.json')
    installed.add_argument('--claude-settings', type=Path, default=Path.home() / '.claude' / 'settings.json')
    installed.add_argument('--codex-hooks', type=Path, default=Path.home() / '.codex' / 'hooks.json')
    installed.add_argument('--grok-hooks', type=Path, default=Path.home() / '.grok' / 'hooks')
    cal = commands.add_parser('calibrate', help='Replay historical task-class cases and record model/effort')
    cal.add_argument('--class', dest='task_class', required=True)
    cal.add_argument('--runner', choices=['claude', 'codex', 'grok', 'cursor'], required=True)
    cal.add_argument('--execution', choices=['current', 'api'], default='current')
    cal.add_argument('--budget-usd', type=positive)
    cal.add_argument('--time-limit', type=positive, required=True)
    cal.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    cal.add_argument('--env-file', type=Path, default=Path('.env'))
    cal.add_argument('--workspace', type=Path, default=Path.cwd())
    cal.add_argument('--baseline-model')
    cal.add_argument('--baseline-provider')
    cal.add_argument('--effort')
    cal.add_argument('--repeats', type=positive_integer, default=3)
    cal.add_argument('--force', action='store_true')
    cal.add_argument('--resume')
    cal.add_argument('--native-home', type=Path)
    return root


def main(argv=None):
    args = vars(parser().parse_args(argv))
    command = args.pop('command')
    try:
        if command == 'models':
            from .providers import Provider, load_providers, discover_models
            results = []
            providers = {'openrouter': Provider('openrouter', 'https://openrouter.ai/api/v1', '')} if args['openrouter'] else load_providers(args['env_file'])
            for name, provider in providers.items():
                try:
                    results.append({'provider': name, 'models': discover_models(provider)})
                except Exception as exc:
                    # Provider errors deliberately omit exception bodies: upstream may echo credentials.
                    results.append({'provider': name, 'error': getattr(exc, 'category', type(exc).__name__)})
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return 0 if results and not any('error' in r for r in results) else 1
        if command == 'catalog':
            from .catalog import catalog
            result = catalog(**args)
        elif command == 'isolate':
            from .runner import isolate
            result = isolate(**args)
        elif command == 'configure':
            from .configure import configure
            result = configure(**args)
        elif command == 'report':
            if args.get('run_id'):
                from .optimizer import read_report
                result = read_report(args['run_id'], args['state_dir'], args['format'])
            elif args.get('runner'):
                from .report import report as class_report
                result = class_report(args['runner'], args['state_dir'], days=args.get('days') or 90)
            else:
                raise ValueError('report needs a run id or --runner')
        elif command == 'optimize':
            if args['cases'] < 4:
                raise ValueError('--cases must be at least 4 for normal, boundary, failure, and held-out coverage')
            from .optimizer import optimize
            result = optimize(**args)
        elif command == 'route':
            from .route import route
            if args.get('hook_stdin'):
                payload = json.loads(sys.stdin.read() or '{}')
                prompt = payload.get('prompt') or payload.get('user_prompt') or args.get('prompt') or ''
                model = payload.get('model') or args.get('model')
                effort = payload.get('effort') or args.get('effort')
                workspace = payload.get('cwd') or payload.get('workspace') or args.get('workspace') or Path.cwd()
                result = route(prompt, args['host'], model, effort, workspace, args['state_dir'])
                print(json.dumps({'continue': True, **({'user_message': result['message']} if result.get('ask') else {})},
                                 ensure_ascii=False))
                return 0
            result = route(args['prompt'], args['host'], args.get('model'), args.get('effort'),
                           args.get('workspace') or Path.cwd(), args['state_dir'])
        elif command == 'feedback':
            from .feedback import ask_feedback, record_feedback
            from .classify import classify
            if args.get('hook_stdin'):
                payload = json.loads(sys.stdin.read() or '{}')
                prompt = payload.get('prompt') or payload.get('user_prompt') or ''
                model = payload.get('model') or args.get('model')
                effort = payload.get('effort') or args.get('effort')
                host = args.get('host') or payload.get('host') or 'cursor'
                verdict = payload.get('verdict') or args.get('verdict')
                task_class = args.get('task_class') or classify(prompt)
                if verdict:
                    result = record_feedback(args['state_dir'], task_class, host, model, effort, verdict)
                else:
                    result = ask_feedback(prompt, host, model, effort)
                    if result.get('message'):
                        print(json.dumps({'user_message': result['message']}, ensure_ascii=False))
                        return 0
                print(json.dumps(result, ensure_ascii=False))
                return 0
            result = record_feedback(args['state_dir'], args.get('task_class'), args.get('host'),
                                     args.get('model'), args.get('effort'), args.get('verdict'))
        elif command == 'hook':
            from .hooks import install_hooks
            result = install_hooks(args['cursor_hooks'],
                                  claude_settings=args.get('claude_settings'),
                                  codex_hooks=args.get('codex_hooks'),
                                  grok_hooks=args.get('grok_hooks'))
        elif command == 'calibrate':
            from .calibrate import calibrate
            result = calibrate(**args)
        else:
            from .optimizer import run_profile
            args['profile_path'] = args.pop('profile')
            result = run_profile(**args)
        print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if command == 'run' and isinstance(result, dict) and result.get('status') not in ('completed', 'success', 'ok'):
            return 1
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'harness-opt: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
