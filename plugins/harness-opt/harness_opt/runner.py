"""Native CLI execution; configuration provenance is hashed, never serialized."""
from __future__ import annotations

import hashlib
import fnmatch
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import tomllib


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts)


class WorkspaceSnapshot:
    def __init__(self, workspace: Path, destination: Path):
        self.source = Path(workspace).resolve()
        self.path = Path(destination).resolve()
        if self.path == self.source or self.path.is_relative_to(self.source):
            raise ValueError('Snapshot destination must be outside the source workspace')
        for path in self.source.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Symlink requires an isolated fixture: {path.relative_to(self.source)}')
        if (self.source / '.git').is_file():
            raise ValueError('Linked git worktrees need a standalone checkout fixture')
        shutil.copytree(self.source, self.path)
        self.fingerprint = hashlib.sha256(json.dumps([
            (str(p.relative_to(self.path)), _digest(p), p.stat().st_mode & 0o777)
            for p in sorted(self.path.rglob('*')) if p.is_file()
        ]).encode()).hexdigest()

    def restore(self, destination: Path) -> Path:
        destination = Path(destination).resolve()
        if destination == self.source or destination.is_relative_to(self.source):
            raise ValueError('Cannot restore over the source workspace')
        # copytree deliberately refuses existing destinations, preventing accidental deletion.
        shutil.copytree(self.path, destination)
        return destination


_NATIVE_IGNORES = ('tmp', 'sessions', 'history.jsonl', 'logs', 'debug', 'telemetry', '*.sqlite*', '*.sock')
RUNNERS = ('claude', 'codex', 'grok')
HOSTS = ('claude', 'codex', 'grok', 'cursor')
_NATIVE_DIR = {'claude': '.claude', 'codex': '.codex', 'grok': '.grok'}
_NATIVE_HOME_ENV = {'claude': 'CLAUDE_CONFIG_DIR', 'codex': 'CODEX_HOME', 'grok': 'GROK_HOME'}


def _require_runner(runner):
    if runner not in RUNNERS:
        raise ValueError('runner must be claude, codex, or grok')
    return runner


def _native_files(root):
    root = Path(root).absolute()
    for directory, directories, files in os.walk(root, followlinks=True):
        path = Path(directory)
        resolved = path.resolve()
        # Aliases are copied at both paths; only an ancestor link creates a cycle.
        ancestors = [parent for parent in path.parents if parent == root or root in parent.parents]
        if any(resolved == parent.resolve() for parent in ancestors):
            raise ValueError(f'Native configuration contains a cyclic directory symlink: {path}')
        directories[:] = sorted(name for name in directories if not any(fnmatch.fnmatch(name, pattern) for pattern in _NATIVE_IGNORES))
        for name in sorted(files):
            if not any(fnmatch.fnmatch(name, pattern) for pattern in _NATIVE_IGNORES):
                path = Path(directory) / name
                if path.is_file():
                    yield path


_ISOLATION_RECORD = '.harness-opt-isolation.json'
_EXTERNAL_KEYS = ('hooks', 'mcpServers', 'mcp_servers')
_EXTERNAL_MARKERS = ('mcpServers', '[mcp_servers.', '"hooks"')


def _user_home(native_home=None):
    return Path(native_home).resolve() if native_home else Path.home()


def _native_config_root(runner, native_home=None):
    home = _user_home(native_home)
    directory = _NATIVE_DIR[_require_runner(runner)]
    if native_home:
        return home / directory
    return Path(os.environ.get(_NATIVE_HOME_ENV[runner], home / directory))


def _requires_external_fixture(config, hashes):
    if any(config.get(key) for key in _EXTERNAL_KEYS):
        return True
    return any(any(marker in Path(filename).read_text(errors='replace') for marker in _EXTERNAL_MARKERS)
               for filename in hashes if Path(filename).suffix in ('.json', '.toml'))


def _configuration(runner, workspace, native_home=None):
    home = _user_home(native_home)
    root = _native_config_root(_require_runner(runner), native_home)
    config = {}
    if runner == 'claude':
        paths = [root / 'settings.json', workspace / '.claude/settings.json',
                 workspace / '.claude/settings.local.json']
        for path in paths:
            if path.is_file():
                config.update(json.loads(path.read_text()))
        paths += [home / '.claude.json', root / 'CLAUDE.md', workspace / 'CLAUDE.md', workspace / '.mcp.json']
    elif runner == 'codex':
        paths = [root / 'config.toml', workspace / '.codex/config.toml']
        for path in paths:
            if path.is_file():
                config.update(tomllib.loads(path.read_text()))
        paths += [root / 'AGENTS.md', workspace / 'AGENTS.md']
    else:
        paths = [root / 'config.toml', workspace / '.grok/config.toml']
        for path in paths:
            if path.is_file():
                config.update(tomllib.loads(path.read_text()))
        models = config.get('models') if isinstance(config.get('models'), dict) else {}
        if models.get('default'):
            config['model'] = models['default']
        if models.get('default_reasoning_effort'):
            config['model_reasoning_effort'] = models['default_reasoning_effort']
        paths += [root / 'AGENTS.md', workspace / 'AGENTS.md']
    paths.extend(_native_files(root))
    paths.extend(_native_files(workspace / _NATIVE_DIR[runner]))
    if runner == 'codex':
        paths.extend(_native_files(workspace / '.agents'))
        paths.extend(_native_files(home / '.agents'))
    return config, {str(p): _digest(p) for p in paths if p.is_file()}


def _environment_fingerprint():
    settings = {key: value for key, value in os.environ.items()
                if key.startswith(('ANTHROPIC_', 'CLAUDE_', 'CODEX_', 'OPENAI_', 'GROK_', 'XAI_'))}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _assert_not_live_native_home(runner, destination):
    dest = Path(destination).resolve()
    live_home = Path.home().resolve()
    live_root = _native_config_root(runner).resolve()
    live_agents = (live_home / '.agents').resolve()
    if dest == live_home:
        raise ValueError('Native home fixture cannot be the live user home')
    if dest == live_root or dest == live_agents or dest.is_relative_to(live_root) or dest.is_relative_to(live_agents):
        raise ValueError('Native home fixture cannot be the live native configuration directory')
    if (dest / _NATIVE_DIR[_require_runner(runner)]).resolve() == live_root:
        raise ValueError('Native home fixture cannot be the live native configuration directory')


def verify_native_home(runner, destination):
    destination = Path(destination).expanduser().resolve()
    _assert_not_live_native_home(runner, destination)
    record_path = destination / _ISOLATION_RECORD
    if not record_path.is_file():
        raise ValueError('Native home is missing the harness-opt isolation record; run harness-opt isolate')
    try:
        record = json.loads(record_path.read_text())
    except ValueError:
        raise ValueError('Native home isolation record is invalid') from None
    if record.get('kind') != 'native-home' or record.get('runner') != runner or record.get('created_by') != 'harness-opt':
        raise ValueError('Native home isolation record is invalid')
    config, hashes = _configuration(runner, destination, native_home=destination)
    if _requires_external_fixture(config, hashes):
        raise ValueError('Native home fixture is no longer isolated from hooks/MCP; re-run harness-opt isolate --force')
    return destination


def _write_minimal_native_config(runner, destination, config):
    if runner == 'codex':
        root = destination / '.codex'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lines = []
        if config.get('model'):
            lines.append('model = ' + json.dumps(config['model']))
        if config.get('model_reasoning_effort'):
            lines.append('model_reasoning_effort = ' + json.dumps(config['model_reasoning_effort']))
        (root / 'config.toml').write_text('\n'.join(lines) + ('\n' if lines else ''))
        live_auth = _native_config_root('codex') / 'auth.json'
        if live_auth.is_file():
            shutil.copy2(live_auth, root / 'auth.json')
            os.chmod(root / 'auth.json', 0o600)
        return
    if runner == 'grok':
        root = destination / '.grok'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lines = ['[models]']
        if config.get('model'):
            lines.append('default = ' + json.dumps(config['model']))
        if config.get('model_reasoning_effort'):
            lines.append('default_reasoning_effort = ' + json.dumps(config['model_reasoning_effort']))
        (root / 'config.toml').write_text('\n'.join(lines) + '\n')
        live_auth = _native_config_root('grok') / 'auth.json'
        if live_auth.is_file():
            shutil.copy2(live_auth, root / 'auth.json')
            os.chmod(root / 'auth.json', 0o600)
        return
    root = destination / '.claude'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = {key: config[key] for key in ('model', 'effortLevel') if config.get(key)}
    (root / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    live_login = Path.home() / '.claude.json'
    if live_login.is_file():
        try:
            data = json.loads(live_login.read_text())
        except ValueError:
            data = {}
        if isinstance(data, dict):
            for key in _EXTERNAL_KEYS:
                data.pop(key, None)
            login = destination / '.claude.json'
            login.write_text(json.dumps(data, indent=2) + '\n')
            os.chmod(login, 0o600)


def isolate(runner, destination=None, force=False):
    _require_runner(runner)
    destination = Path(destination or (Path.home() / '.cache' / 'harness-opt' / 'native-home' / runner)).expanduser().resolve()
    if destination.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Store the native home fixture outside the installed plugin/package directory')
    _assert_not_live_native_home(runner, destination)
    record = destination / _ISOLATION_RECORD
    if destination.exists() and any(destination.iterdir()) and not force:
        if record.is_file():
            verify_native_home(runner, destination)
            return {'status': 'isolated', 'runner': runner, 'native_home': str(destination),
                    'external_isolation_verified': True, 'reused': True}
        raise ValueError('Native home destination exists; pass --force to replace it')
    if destination.exists() and force:
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    live_config, _ = _configuration(runner, destination)
    _write_minimal_native_config(runner, destination, live_config)
    (destination / _ISOLATION_RECORD).write_text(json.dumps({
        'kind': 'native-home', 'runner': runner, 'created_by': 'harness-opt'}, indent=2) + '\n')
    os.chmod(destination / _ISOLATION_RECORD, 0o600)
    os.chmod(destination, 0o700)
    verify_native_home(runner, destination)
    return {'status': 'isolated', 'runner': runner, 'native_home': str(destination),
            'external_isolation_verified': True, 'reused': False}


def capture_profile(runner, workspace: Path, model=None, effort=None, current=False, native_home=None) -> dict:
    workspace = Path(workspace).resolve()
    native_home = Path(native_home).expanduser().resolve() if native_home else None
    if native_home:
        verify_native_home(runner, native_home)
    inherited = {'claude': ('CLAUDE.md', '.claude'), 'grok': ('AGENTS.md', '.grok'),
                 'codex': ('AGENTS.md', '.codex', '.agents')}[_require_runner(runner)]
    for ancestor in workspace.parents:
        if ancestor == Path.home().resolve():
            continue
        if any((ancestor / name).exists() for name in inherited):
            raise ValueError('Ancestor instructions/configuration require selecting that ancestor as --workspace')
    config, hashes = _configuration(runner, workspace, native_home=native_home)
    model = model or (os.environ.get('ANTHROPIC_MODEL') if runner == 'claude' else None) or config.get('model')
    effort = effort or (os.environ.get('CLAUDE_CODE_EFFORT_LEVEL') if runner == 'claude' else None) or config.get('effortLevel' if runner == 'claude' else 'model_reasoning_effort')
    if not current and (not model or not effort):
        raise ValueError('Baseline model and effort must be explicit or present in native configuration')
    for filename in hashes:
        path = Path(filename)
        if 'agents' in path.parts and path.suffix in ('.toml', '.json', '.md'):
            content = path.read_text(errors='replace')
            if not current and any(marker in content for marker in ('model_provider', 'ANTHROPIC_BASE_URL', 'OPENAI_BASE_URL', 'api_base', 'base_url')):
                raise ValueError('Fixed subagent provider override cannot be guaranteed to route through the metered gateway')
    for agent in (config.get('agents') or {}).values():
        if isinstance(agent, dict) and agent.get('config_file'):
            candidate = Path(agent['config_file']).expanduser()
            if not candidate.is_absolute():
                candidate = _native_config_root(runner, native_home) / candidate
            if str(candidate) not in hashes:
                raise ValueError('External subagent configuration requires an isolated, captured fixture')
    binary = shutil.which(runner)
    if not binary:
        raise ValueError(f'{runner} CLI is not installed')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    requires = _requires_external_fixture(config, hashes)
    verified = bool(native_home) and not requires
    return {'runner': runner, 'current': current, 'model': model, 'effort': effort, 'version': version,
            'workspace': str(workspace), 'configuration_hashes': hashes, 'native_home': str(native_home) if native_home else None,
            'environment_fingerprint': _environment_fingerprint(),
            'execution_options': {'claude': ['-p', '--output-format=json'],
                                  'grok': ['--prompt-file', '--output-format=json', '--always-approve'],
                                  'codex': ['exec', '--json', '--ephemeral', '--skip-git-repo-check']}[runner],
            'capture_scope': 'explicit model/effort and native disk configuration; session-only overrides require explicit reproduction',
            'isolation': ('verified native-home fixture without live hooks/MCP' if verified
                          else 'filesystem copies only; externally sandbox hooks and MCP before execution'),
            'external_isolation_verified': verified,
            'authentication_scope': 'Existing native environment and copied credential files; keychain access under isolated HOME is runner/platform dependent',
            'requires_external_fixture': requires,
            'preservation_limits': ['Parent-directory instructions and session-only flags are not captured',
                                    'Absolute hook/plugin paths and external MCP state require isolated fixtures',
                                    'Workspace trust is not transferred to copied directory paths']}


def parse_grok_models(output):
    ids = []
    for line in output.splitlines():
        match = re.match(r'\s*[*+-]\s+([A-Za-z0-9._:-]+)', line)
        if match:
            ids.append(match.group(1))
    return list(dict.fromkeys(ids))


def parse_grok_effort_error(text):
    match = re.search(r'use one of:\s*([^\n]+)', text or '')
    if not match:
        return None
    return [part.strip().strip("'\"") for part in match.group(1).split(',') if part.strip()]


def grok_allowed_efforts(binary, model_id, env=None):
    prompt = tempfile.NamedTemporaryFile('w', delete=False)
    try:
        prompt.write('.')
        prompt.close()
        proc = subprocess.run(
            [binary, '--prompt-file', prompt.name, '--model', model_id,
             '--effort', '__harness_opt_probe__', '--output-format', 'json'],
            capture_output=True, text=True, timeout=30, env=env)
    finally:
        Path(prompt.name).unlink(missing_ok=True)
    return parse_grok_effort_error(proc.stderr) or parse_grok_effort_error(proc.stdout)


EFFORT_ORDER = ('low', 'medium', 'high', 'xhigh', 'ultra', 'max')


def parse_listed_models(data):
    rows = []
    if not isinstance(data, list):
        return rows
    for item in data:
        if isinstance(item, str) and item.strip():
            rows.append({'id': item.strip(), 'provider': 'native', 'efforts': []})
        elif isinstance(item, dict):
            model_id = item.get('id') or item.get('model')
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            efforts = item.get('efforts') if isinstance(item.get('efforts'), list) else []
            rows.append({'id': model_id.strip(), 'provider': 'native',
                         'efforts': [e for e in efforts if isinstance(e, str) and e]})
    return rows


def efforts_to_ceiling(ceiling_effort, seen=()):
    if ceiling_effort in EFFORT_ORDER:
        return [item for item in EFFORT_ORDER if EFFORT_ORDER.index(item) <= EFFORT_ORDER.index(ceiling_effort)]
    extra = [item for item in seen if isinstance(item, str) and item]
    return extra or ([ceiling_effort] if ceiling_effort else [])


def parse_cursor_cli_config(data):
    if not isinstance(data, dict):
        return [], {}
    ids = []

    def add(value):
        if isinstance(value, str) and value.strip():
            ids.append(value.strip())

    for key in ('model', 'selectedModel'):
        block = data.get(key)
        if isinstance(block, dict):
            add(block.get('modelId') or block.get('displayModelId'))
    history = data.get('modelSelectionHistory')
    if isinstance(history, list):
        for item in history:
            add(item)
    params = data.get('modelParameters') if isinstance(data.get('modelParameters'), dict) else {}
    for key in params:
        add(key)
    listed = data.get('availableModels', data.get('models'))
    extra = parse_listed_models(listed) if isinstance(listed, list) else []
    for row in extra:
        add(row['id'])
    selected = data.get('selectedModel') if isinstance(data.get('selectedModel'), dict) else None
    if not selected and isinstance(data.get('model'), dict):
        selected = data['model']
    model_id = selected.get('modelId') if isinstance(selected, dict) else None
    effort = None
    for item in (selected.get('parameters') or []) if isinstance(selected, dict) else []:
        if isinstance(item, dict) and item.get('id') == 'effort' and isinstance(item.get('value'), str):
            effort = item['value']
    if not effort and isinstance(params.get(model_id), list):
        for item in params[model_id]:
            if isinstance(item, dict) and item.get('id') == 'effort' and isinstance(item.get('value'), str):
                effort = item['value']
    ceiling = {'model': model_id, 'effort': effort} if model_id else {}
    by_id = {row['id']: row.get('efforts') or [] for row in extra}
    models = []
    for item in dict.fromkeys(ids):
        seen = []
        for row in params.get(item) or []:
            if isinstance(row, dict) and row.get('id') == 'effort' and isinstance(row.get('value'), str):
                seen.append(row['value'])
        listed_efforts = by_id.get(item) or []
        cap = effort if item == ceiling.get('model') else (seen[-1] if seen else (listed_efforts[-1] if listed_efforts else None))
        models.append({'id': item, 'provider': 'native',
                       'efforts': listed_efforts or efforts_to_ceiling(cap, seen)})
    return models, ceiling


def disk_ceiling(host, profile=None):
    profile = profile or {}
    if host == 'cursor':
        path = Path.home() / '.cursor' / 'cli-config.json'
        if not path.is_file():
            return {}
        try:
            _, ceiling = parse_cursor_cli_config(json.loads(path.read_text()))
        except (ValueError, OSError):
            return {}
        return ceiling
    if host not in RUNNERS:
        return {}
    root = _native_config_root(host, profile.get('native_home'))
    if host == 'claude':
        path = root / 'settings.json'
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return {}
        model, effort = data.get('model'), data.get('effortLevel')
        settings = data.get('modelSettings') if isinstance(data.get('modelSettings'), dict) else {}
        if not model and settings:
            model = next((key for key in settings if isinstance(key, str) and key), None)
        if isinstance(model, str) and isinstance(settings.get(model), dict):
            effort = settings[model].get('effortLevel') or effort
        return {'model': model, 'effort': effort} if model else {}
    path = root / 'config.toml'
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except (ValueError, OSError):
        return {}
    if host == 'grok':
        models = data.get('models') if isinstance(data.get('models'), dict) else {}
        model = models.get('default')
        effort = models.get('default_reasoning_effort')
        return {'model': model, 'effort': effort} if model else {}
    model, effort = data.get('model'), data.get('model_reasoning_effort')
    return {'model': model, 'effort': effort} if model else {}


def catalog_fingerprint(models):
    payload = [(m.get('id'), tuple(m.get('efforts') or [])) for m in models]
    return hashlib.sha256(repr(payload).encode()).hexdigest()


def _parse_models_stdout(text):
    text = text or ''
    try:
        parsed = json.loads(text)
    except ValueError:
        ids = parse_grok_models(text)
        return parse_listed_models(ids)
    if isinstance(parsed, dict):
        parsed = parsed.get('models')
    return parse_listed_models(parsed)


def _disk_models(runner, profile):
    if runner == 'cursor':
        path = Path.home() / '.cursor' / 'cli-config.json'
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return []
        models, _ = parse_cursor_cli_config(data)
        return models
    if runner not in RUNNERS:
        return []
    root = _native_config_root(runner, profile.get('native_home'))
    if runner == 'claude':
        path = root / 'settings.json'
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return []
        listed = data.get('availableModels', data.get('models'))
        rows = parse_listed_models(listed) if isinstance(listed, list) else []
        settings = data.get('modelSettings') if isinstance(data.get('modelSettings'), dict) else {}
        for key, value in settings.items():
            if not isinstance(key, str) or not key.strip():
                continue
            effort = value.get('effortLevel') if isinstance(value, dict) else None
            rows.append({'id': key.strip(), 'provider': 'native',
                         'efforts': efforts_to_ceiling(effort, [effort] if effort else ())})
        return _unique_models(rows)
    path = root / 'config.toml'
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text())
    except (ValueError, OSError):
        return []
    listed = data.get('models')
    if isinstance(listed, dict):
        listed = [{'id': key, **(value if isinstance(value, dict) else {})} for key in listed]
    rows = parse_listed_models(listed) if isinstance(listed, list) else []
    catalog = data.get('model_catalog_json')
    if isinstance(catalog, str) and catalog:
        extra = Path(catalog).expanduser()
        if extra.is_file():
            try:
                rows.extend(parse_codex_catalog(json.loads(extra.read_text())))
            except (ValueError, OSError):
                pass
    if isinstance(data.get('model'), str) and data['model'].strip():
        rows.append({'id': data['model'].strip(), 'provider': 'native',
                     'efforts': efforts_to_ceiling(data.get('model_reasoning_effort'))})
    return _unique_models(rows)


def parse_codex_catalog(data):
    models = data.get('models') if isinstance(data, dict) else data
    rows = []
    if not isinstance(models, list):
        return rows
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = item.get('slug') or item.get('id') or item.get('model')
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        efforts = []
        for level in item.get('supported_reasoning_levels') or []:
            if isinstance(level, dict) and isinstance(level.get('effort'), str) and level['effort']:
                efforts.append(level['effort'])
            elif isinstance(level, str) and level:
                efforts.append(level)
        rows.append({'id': model_id.strip(), 'provider': 'native', 'efforts': efforts})
    return rows


def _unique_models(rows):
    seen = {}
    for row in rows:
        current = seen.get(row['id'])
        if current is None or (row.get('efforts') and not current.get('efforts')):
            seen[row['id']] = row
    return list(seen.values())


def _disk_or_cli_models(runner, profile):
    rows = _disk_models(runner, profile)
    if rows or runner == 'cursor':
        return rows
    binary = shutil.which(runner)
    if not binary:
        return []
    try:
        proc = subprocess.run([binary, 'models'], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return _parse_models_stdout(proc.stdout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def native_models(runner, profile):
    """Native selectable models; never invent IDs. Cursor listing is for report/hooks only."""
    if runner == 'cursor' and (profile or {}).get('measurement'):
        raise ValueError('--runner cursor')
    if runner not in HOSTS:
        raise ValueError('runner must be claude, codex, grok, or cursor')
    profile = profile or {}
    if 'catalog' in profile:
        data = profile['catalog']
        if data and isinstance(data, list) and isinstance(data[0], dict) and 'provider' in data[0]:
            return data
        return parse_listed_models(data)
    if runner == 'grok':
        binary = shutil.which('grok')
        if not binary:
            raise ValueError('grok CLI is not installed')
        env = os.environ.copy()
        native_home = profile.get('native_home')
        if native_home:
            grok_home = Path(native_home) / '.grok'
            if grok_home.is_dir():
                env['GROK_HOME'] = str(grok_home)
        proc = subprocess.run([binary, 'models'], capture_output=True, text=True, timeout=30, env=env)
        if proc.returncode:
            raise ValueError('grok models failed')
        ids = parse_grok_models(proc.stdout)
        if not ids:
            raise ValueError('grok models listed no model IDs')
        captured = profile.get('effort') or ''
        models = []
        for model_id in ids:
            allowed = grok_allowed_efforts(binary, model_id, env)
            if captured and allowed and captured in allowed:
                efforts = [captured]
            elif captured and not allowed and model_id == profile.get('model'):
                efforts = [captured]
            else:
                efforts = ['']
            models.append(dict(id=model_id, provider='native', efforts=efforts))
        return models
    return _disk_or_cli_models(runner, profile)


def _native_events(output):
    if not isinstance(output, str):
        return []
    try:
        parsed = json.loads(output)
        events = parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, TypeError):
        events = []
        for line in output.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return [event for event in events if isinstance(event, dict)]


def native_usage(output, runner):
    """Native counters only: total input includes cached tokens; reasoning is an output subset."""
    empty = {'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None,
             'cache_creation_input_tokens': None, 'reasoning_tokens': None,
             'reported_cost_usd': None, 'scope': 'native CLI aggregate; billing completeness unverified'}
    events = _native_events(output)
    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    if runner in ('claude', 'grok'):
        if runner == 'grok' and any(event.get('type') == 'error' for event in events):
            return empty
        results = [event for event in events if event.get('type') == 'result']
        if runner == 'grok' and not results:
            results = [event for event in events if isinstance(event.get('usage'), dict)]
        if len(results) != 1:
            return empty
        result = results[0]
        usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
        if not usage and isinstance(result.get('modelUsage'), dict) and result['modelUsage']:
            rows = list(result['modelUsage'].values())
            def model_sum(key):
                values = [count(row.get(key)) for row in rows if isinstance(row, dict)]
                return sum(values) if len(values) == len(rows) and all(value is not None for value in values) else None
            usage = {'input_tokens': model_sum('inputTokens'), 'output_tokens': model_sum('outputTokens'),
                     'cache_read_input_tokens': model_sum('cacheReadInputTokens'),
                     'cache_creation_input_tokens': model_sum('cacheCreationInputTokens')}
        regular = count(usage.get('input_tokens'))
        cached = count(usage.get('cache_read_input_tokens'))
        created = count(usage.get('cache_creation_input_tokens'))
        total = regular + cached + created if all(value is not None for value in (regular, cached, created)) else None
        details = usage.get('output_tokens_details') if isinstance(usage.get('output_tokens_details'), dict) else {}
        reported_cost = result.get('total_cost_usd')
        reported_cost = reported_cost if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool) and math.isfinite(reported_cost) and reported_cost >= 0 else None
        reasoning = count(usage.get('reasoning_tokens'))
        if reasoning is None:
            reasoning = count(details.get('thinking_tokens'))
        return {**empty, 'input_tokens': total, 'output_tokens': count(usage.get('output_tokens')),
                'cached_input_tokens': cached, 'cache_creation_input_tokens': created,
                'reasoning_tokens': reasoning,
                'observed_models': sorted(result['modelUsage']) if isinstance(result.get('modelUsage'), dict) else [],
                'reported_cost_usd': reported_cost}
    if any(event.get('type') in ('error', 'turn.failed') for event in events):
        return empty
    turns = [event.get('usage') for event in events if event.get('type') == 'turn.completed']
    if not turns or any(not isinstance(usage, dict) for usage in turns):
        return empty
    def aggregate(key):
        values = [count(usage.get(key)) for usage in turns]
        return sum(values) if all(value is not None for value in values) else None
    return {**empty, 'input_tokens': aggregate('input_tokens'), 'output_tokens': aggregate('output_tokens'),
            'cached_input_tokens': aggregate('cached_input_tokens'),
            'cache_creation_input_tokens': aggregate('cache_write_input_tokens'),
            'reasoning_tokens': aggregate('reasoning_output_tokens')}


def _stored_secrets(hashes):
    secrets = set()
    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if any(marker in key.lower().replace('_', '') for marker in ('apikey', 'token', 'secret', 'password')) and isinstance(child, str) and len(child) >= 6:
                    secrets.add(child)
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    for filename in hashes:
        path = Path(filename)
        try:
            if path.suffix == '.json':
                collect(json.loads(path.read_text()))
            elif path.suffix == '.toml':
                collect(tomllib.loads(path.read_text()))
        except (ValueError, UnicodeError):
            continue
    return secrets


def _redact(text, stored_secrets=()):
    for value in stored_secrets:
        text = text.replace(value, '[REDACTED]')
    for key, value in os.environ.items():
        if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD')) and len(value) >= 6:
            text = text.replace(value, '[REDACTED]')
    return re.sub(r'\b(?:sk-|ghp_)[A-Za-z0-9_-]{12,}', '[REDACTED]', text)


def _install_copy(source, destination):
    if destination.resolve().is_relative_to(source.resolve()):
        with tempfile.TemporaryDirectory(prefix='harness-skill-stage-') as temp:
            staged = Path(temp) / 'source'
            shutil.copytree(source, staged)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)


def public_skill_files(target):
    target = Path(target)
    if target.is_file():
        return [target] if target.name == 'SKILL.md' else []
    plugin = (target / 'plugin.json').is_file() or any(
        (target / manifest / 'plugin.json').is_file() for manifest in ('.claude-plugin', '.codex-plugin', '.grok-plugin'))
    if not plugin and (target / 'SKILL.md').is_file():
        return [target / 'SKILL.md']
    return sorted((target / 'skills').glob('*/SKILL.md'))


def _activate(runner, workspace, target, entrypoint=None):
    target = Path(target).resolve()
    if target.is_file():
        target = target.parent
    manifest = target / '.claude-plugin/plugin.json'
    if runner == 'codex':
        manifest = target / '.codex-plugin/plugin.json'
        if not manifest.is_file() and (target / '.claude-plugin/plugin.json').is_file():
            raise ValueError('Plugin has no native Codex manifest; select a skill or supply a Codex plugin')
    elif runner == 'grok':
        manifest = next((path for path in (target / 'plugin.json', target / '.claude-plugin/plugin.json',
                                           target / '.grok-plugin/plugin.json') if path.is_file()), manifest)
    if manifest.is_file():
        destination = workspace / '.harness-plugins' / target.name
        if destination.resolve() != target:
            _install_copy(target, destination)
        metadata = json.loads(manifest.read_text())
        plugin_name = metadata.get('name', target.name)
        skills = public_skill_files(destination)
        if entrypoint:
            source_entrypoint = workspace / entrypoint
            if not source_entrypoint.is_relative_to(target):
                raise ValueError('Entrypoint is outside the target plugin')
            chosen = destination / source_entrypoint.relative_to(target)
            skills = [skill for skill in skills if skill == chosen]
        if not skills:
            raise ValueError('Plugin has no public skill entry points')
        invocations = []
        for skill in skills:
            match = re.search(r'^name:\s*[\"\']?([A-Za-z0-9_-]+)', skill.read_text(), re.MULTILINE)
            name = match.group(1) if match else skill.parent.name
            invocations.append('/' + plugin_name + ':' + name if runner in ('claude', 'grok') else '$' + name)
        return (['--plugin-dir', str(destination)] if runner == 'claude' else []), ' '.join(invocations) + '\n'
    skills = public_skill_files(target)
    if not skills:
        raise ValueError('Target has no native skill entry point')
    if entrypoint:
        selected = (workspace / entrypoint).resolve()
        skills = [skill for skill in skills if skill.resolve() == selected]
        if not skills:
            raise ValueError('Entrypoint is not a public target skill')
    names = []
    for skill in skills:
        match = re.search(r'^name:\s*[\"\']?([A-Za-z0-9_-]+)', skill.read_text(), re.MULTILINE)
        name = match.group(1) if match else skill.parent.name
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid native skill name')
        destination = workspace / {'claude': '.claude', 'grok': '.grok', 'codex': '.agents'}[runner] / 'skills' / name
        if destination.resolve() != skill.parent.resolve():
            if destination.exists():
                raise ValueError(f'Native skill installation collision: {name}')
            _install_copy(skill.parent, destination)
        names.append(('/' if runner in ('claude', 'grok') else '$') + name)
    return [], ' '.join(names) + '\n'


def execute(profile: dict, workspace: Path, prompt: str, gateway_url: str | None,
            timeout: float, target: Path | None = None) -> dict:
    workspace = Path(workspace).resolve()
    gateway_key = profile.get('gateway_api_key')
    if gateway_url and profile.get('runner') == 'grok':
        raise ValueError('Grok has no metered API-gateway adapter; use --execution current')
    if gateway_url and not gateway_key:
        raise ValueError('Gateway execution requires an ephemeral gateway_api_key')
    if workspace == Path(profile['workspace']).resolve():
        raise ValueError('Execution requires an isolated workspace')
    if profile.get('native_home'):
        verify_native_home(profile['runner'], Path(profile['native_home']))
    if profile.get('environment_fingerprint') and profile['environment_fingerprint'] != _environment_fingerprint():
        raise ValueError('Native environment changed since baseline capture')
    _, current_hashes = _configuration(profile['runner'], Path(profile['workspace']), native_home=profile.get('native_home'))
    if current_hashes != profile.get('configuration_hashes', {}):
        raise ValueError('Native configuration changed since baseline capture')
    runner = profile['runner']
    binary = shutil.which(runner)
    if not binary:
        raise ValueError(f'{runner} CLI is not installed')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    if version != profile['version']:
        raise ValueError('Runner version changed since baseline capture')
    if target:
        target = Path(target).resolve()
        original = Path(profile['workspace']).resolve()
        if target.is_relative_to(original):
            target = workspace / target.relative_to(original)
    args, prefix = _activate(runner, workspace, target, profile.get('entrypoint')) if target else ([], '')
    env = dict(os.environ)
    env.pop('CLAUDECODE', None)
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='harness-native-') as temp:
        isolated = Path(temp)
        home = Path(profile['native_home']).resolve() if profile.get('native_home') else Path.home()
        # Isolated native-home fixtures omit live hooks/MCP; otherwise copy native configuration as-is.
        native_directories = {
            'claude': [('.claude', 'CLAUDE_CONFIG_DIR')],
            'grok': [('.grok', 'GROK_HOME')],
            'codex': [('.codex', 'CODEX_HOME'), ('.agents', None)],
        }[runner]
        for directory, override in native_directories:
            if profile.get('native_home'):
                source = home / directory
            else:
                source = Path(env.get(override, Path.home() / directory)) if override else Path.home() / directory
            if source.is_dir():
                shutil.copytree(source, isolated / directory, ignore=shutil.ignore_patterns(*_NATIVE_IGNORES), symlinks=False)
            (isolated / directory).mkdir(parents=True, exist_ok=True)
            if override:
                env[override] = str(isolated / directory)
        claude_login = home / '.claude.json'
        if runner == 'claude' and claude_login.is_file():
            shutil.copy2(claude_login, isolated / '.claude.json')
        env['HOME'] = str(isolated)
        if runner == 'codex' and target and (target / '.codex-plugin/plugin.json').is_file():
            plugin_copy = workspace / '.harness-plugins' / target.name
            plugin_name = json.loads((plugin_copy / '.codex-plugin/plugin.json').read_text())['name']
            marketplace = isolated / 'marketplace'
            (marketplace / '.agents/plugins').mkdir(parents=True)
            shutil.copytree(plugin_copy, marketplace / 'plugin')
            (marketplace / '.agents/plugins/marketplace.json').write_text(json.dumps({
                'name': 'harness-local-evaluation', 'plugins': [{
                    'name': plugin_name, 'source': {'source': 'local', 'path': './plugin'},
                    'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}
                }]}))
            for install_args in (['marketplace', 'add', str(marketplace), '--json'],
                                 ['add', plugin_name + '@harness-local-evaluation', '--json']):
                installed = subprocess.run([binary, 'plugin', *install_args], env=env, cwd=workspace,
                                           capture_output=True, text=True, timeout=max(.001, min(timeout - (time.monotonic() - start), 60)))
                if installed.returncode:
                    raise ValueError('Native Codex plugin installation failed: ' + _redact(installed.stderr))
        if runner == 'grok':
            if gateway_url:
                raise ValueError('Grok has no metered API-gateway adapter; use --execution current')
            plugin_copy = workspace / '.harness-plugins' / target.name if target else None
            if plugin_copy and plugin_copy.is_dir():
                plugins = isolated / '.grok/plugins' / target.name
                if not plugins.exists():
                    _install_copy(plugin_copy, plugins)
            (isolated / '.grok/trusted_folders.toml').write_text(
                f'[folders.{json.dumps(str(workspace))}]\ntrusted = true\n')
        if runner == 'claude':
            command = [binary, '-p', '--output-format', 'json', *args]
            if profile.get('model'):
                command += ['--model', profile['model']]
            if profile.get('effort'):
                command += ['--effort', profile['effort']]
            if gateway_url:
                env.update(ANTHROPIC_BASE_URL=gateway_url, ANTHROPIC_API_KEY=gateway_key, ANTHROPIC_AUTH_TOKEN=gateway_key)
            stdin_payload = prefix + prompt
        elif runner == 'grok':
            prompt_file = isolated / 'prompt.txt'
            prompt_file.write_text(prefix + prompt)
            command = [binary, '--prompt-file', str(prompt_file), '--output-format', 'json', '--always-approve']
            if profile.get('model'):
                command += ['--model', profile['model']]
            if profile.get('effort'):
                command += ['--effort', profile['effort']]
            stdin_payload = ''
        else:
            command = [binary, 'exec', '--json', '--ephemeral', '--skip-git-repo-check', *args]
            if profile.get('model'):
                command += ['--model', profile['model']]
            if profile.get('effort'):
                command += ['-c', 'model_reasoning_effort=' + json.dumps(profile['effort'])]
            if gateway_url:
                command += ['-c', 'model_provider="harness_opt"', '-c', 'model_providers.harness_opt.name="harness-opt"', '-c', 'model_providers.harness_opt.base_url=' + json.dumps(gateway_url.rstrip('/') + '/v1'), '-c', 'model_providers.harness_opt.wire_api="responses"', '-c', 'model_providers.harness_opt.env_key="HARNESS_GATEWAY_TOKEN"']
                env['HARNESS_GATEWAY_TOKEN'] = gateway_key
            command.append('-')
            stdin_payload = prefix + prompt
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError('Native configuration preparation exhausted the time limit')
        proc = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        status = 'completed'
        try:
            stdout, stderr = proc.communicate(stdin_payload, timeout=remaining)
            if proc.returncode:
                status = 'runner_error'
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            status = 'timeout'
    if gateway_key:
        stdout, stderr = stdout.replace(gateway_key, '[REDACTED]'), stderr.replace(gateway_key, '[REDACTED]')
    stored_secrets = _stored_secrets(current_hashes)
    usage = native_usage(stdout, runner)
    for event in _native_events(stdout):
        if status != 'timeout' and (event.get('is_error') is True or event.get('type') in ('error', 'turn.failed')):
            status = 'runner_error'
    authentication_guidance = None
    if not gateway_url and status == 'runner_error' and re.search(r'not logged in|please (?:run )?/?login|authentication (?:required|failed)|invalid (?:api key|authentication)|unauthorized|401', stdout + '\n' + stderr, re.IGNORECASE):
        status = 'authentication_required'
        authentication_guidance = 'Existing native login was unavailable in the isolated configuration. Use an already authenticated native credential file/environment; keychain-only login may require runner support. No new API key is required by harness-opt.'
    return {'status': status, 'authentication_guidance': authentication_guidance, 'output': _redact(stdout, stored_secrets), 'stderr': _redact(stderr, stored_secrets),
            'duration': time.monotonic() - start, 'version': version, 'returncode': proc.returncode,
            'native_usage': usage, 'usage': usage,
            'usage_source': 'native_runner' if usage['input_tokens'] is not None or usage['output_tokens'] is not None else 'unknown',
            'external_isolation_verified': profile.get('external_isolation_verified', False),
            'artifacts': {str(p.relative_to(workspace)): _digest(p) for p in _files(workspace)}}
