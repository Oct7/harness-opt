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
    opt = commands.add_parser('optimize', help='Generate cases, measure, compare, and report')
    opt.add_argument('target', type=Path)
    opt.add_argument('--runner', choices=['claude', 'codex'], required=True)
    opt.add_argument('--execution', choices=['current', 'api'], default='current',
                     help='Current native login/model (default), or separately metered API experiments')
    opt.add_argument('--mode', choices=['all', 'steps', 'speed', 'cost', 'structure'], default='all')
    opt.add_argument('--budget-usd', type=positive, help='Required only for --execution api')
    opt.add_argument('--time-limit', type=positive, required=True, help='Wall-clock seconds')
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
    report = commands.add_parser('report', help='Read a saved report')
    report.add_argument('run_id')
    report.add_argument('--state-dir', type=Path, default=Path.home() / '.cache' / 'harness-opt')
    report.add_argument('--format', choices=['json', 'markdown'], default='markdown')
    run = commands.add_parser('run', help='Execute a verified profile in an isolated workspace')
    run.add_argument('profile', type=Path)
    run.add_argument('task')
    run.add_argument('--budget-usd', type=positive, help='Required for API profiles; omitted for current-environment profiles')
    run.add_argument('--time-limit', type=positive, required=True)
    run.add_argument('--env-file', type=Path, default=Path('.env'))
    run.add_argument('--workspace', type=Path, default=Path.cwd())
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
        if command == 'configure':
            from .configure import configure
            result = configure(**args)
        elif command == 'report':
            from .optimizer import read_report
            result = read_report(args['run_id'], args['state_dir'], args['format'])
        elif command == 'optimize':
            if args['cases'] < 4:
                raise ValueError('--cases must be at least 4 for normal, boundary, failure, and held-out coverage')
            from .optimizer import optimize
            result = optimize(**args)
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
