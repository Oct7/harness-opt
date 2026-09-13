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


def _native_files(root):
    visited = set()
    for directory, directories, files in os.walk(root, followlinks=True):
        resolved = Path(directory).resolve()
        if resolved in visited:
            raise ValueError('Native configuration contains a cyclic or duplicate directory symlink')
        visited.add(resolved)
        directories[:] = sorted(name for name in directories if not any(fnmatch.fnmatch(name, pattern) for pattern in _NATIVE_IGNORES))
        for name in sorted(files):
            if not any(fnmatch.fnmatch(name, pattern) for pattern in _NATIVE_IGNORES):
                path = Path(directory) / name
                if path.is_file():
                    yield path


def _configuration(runner, workspace):
    home = Path.home()
    if runner == 'claude':
        root = Path(os.environ.get('CLAUDE_CONFIG_DIR', home / '.claude'))
        paths = [root / 'settings.json', workspace / '.claude/settings.json',
                 workspace / '.claude/settings.local.json']
        config = {}
        for path in paths:
            if path.is_file():
                config.update(json.loads(path.read_text()))
        paths += [home / '.claude.json', root / 'CLAUDE.md', workspace / 'CLAUDE.md', workspace / '.mcp.json']
    elif runner == 'codex':
        root = Path(os.environ.get('CODEX_HOME', home / '.codex'))
        paths = [root / 'config.toml', workspace / '.codex/config.toml']
        config = {}
        for path in paths:
            if path.is_file():
                config.update(tomllib.loads(path.read_text()))
        paths += [root / 'AGENTS.md', workspace / 'AGENTS.md']
    else:
        raise ValueError('runner must be claude or codex')
    paths.extend(_native_files(root))
    paths.extend(_native_files(workspace / ('.claude' if runner == 'claude' else '.codex')))
    if runner == 'codex':
        paths.extend(_native_files(workspace / '.agents'))
        paths.extend(_native_files(home / '.agents'))
    return config, {str(p): _digest(p) for p in paths if p.is_file()}


def _environment_fingerprint():
    settings = {key: value for key, value in os.environ.items()
                if key.startswith(('ANTHROPIC_', 'CLAUDE_', 'CODEX_', 'OPENAI_'))}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def capture_profile(runner, workspace: Path, model=None, effort=None, current=False) -> dict:
    workspace = Path(workspace).resolve()
    inherited = ('CLAUDE.md', '.claude') if runner == 'claude' else ('AGENTS.md', '.codex', '.agents')
    for ancestor in workspace.parents:
        if ancestor == Path.home().resolve():
            continue
        if any((ancestor / name).exists() for name in inherited):
            raise ValueError('Ancestor instructions/configuration require selecting that ancestor as --workspace')
    config, hashes = _configuration(runner, workspace)
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
                candidate = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / candidate
            if str(candidate) not in hashes:
                raise ValueError('External subagent configuration requires an isolated, captured fixture')
    binary = shutil.which(runner)
    if not binary:
        raise ValueError(f'{runner} CLI is not installed')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    return {'runner': runner, 'current': current, 'model': model, 'effort': effort, 'version': version,
            'workspace': str(workspace), 'configuration_hashes': hashes,
            'environment_fingerprint': _environment_fingerprint(),
            'execution_options': ['-p', '--output-format=json'] if runner == 'claude' else ['exec', '--json', '--ephemeral', '--skip-git-repo-check'],
            'capture_scope': 'explicit model/effort and native disk configuration; session-only overrides require explicit reproduction',
            'isolation': 'filesystem copies only; externally sandbox hooks and MCP before execution',
            'external_isolation_verified': False,
            'authentication_scope': 'Existing native environment and copied credential files; keychain access under isolated HOME is runner/platform dependent',
            'requires_external_fixture': any(config.get(key) for key in ('hooks', 'mcpServers', 'mcp_servers')) or any(
                any(marker in Path(filename).read_text(errors='replace') for marker in ('mcpServers', '[mcp_servers.', '"hooks"'))
                for filename in hashes if Path(filename).suffix in ('.json', '.toml')),
            'preservation_limits': ['Parent-directory instructions and session-only flags are not captured',
                                    'Absolute hook/plugin paths and external MCP state require isolated fixtures',
                                    'Workspace trust is not transferred to copied directory paths']}


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
    if runner == 'claude':
        results = [event for event in events if event.get('type') == 'result']
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
        return {**empty, 'input_tokens': total, 'output_tokens': count(usage.get('output_tokens')),
                'cached_input_tokens': cached, 'cache_creation_input_tokens': created,
                'reasoning_tokens': count(details.get('thinking_tokens')),
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
    plugin = any((target / manifest / 'plugin.json').is_file() for manifest in ('.claude-plugin', '.codex-plugin'))
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
            invocations.append('/' + plugin_name + ':' + name if runner == 'claude' else '$' + name)
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
        destination = workspace / ('.claude' if runner == 'claude' else '.agents') / 'skills' / name
        if destination.resolve() != skill.parent.resolve():
            if destination.exists():
                raise ValueError(f'Native skill installation collision: {name}')
            _install_copy(skill.parent, destination)
        names.append(('/' if runner == 'claude' else '$') + name)
    return [], ' '.join(names) + '\n'


def execute(profile: dict, workspace: Path, prompt: str, gateway_url: str | None,
            timeout: float, target: Path | None = None) -> dict:
    workspace = Path(workspace).resolve()
    gateway_key = profile.get('gateway_api_key')
    if gateway_url and not gateway_key:
        raise ValueError('Gateway execution requires an ephemeral gateway_api_key')
    if workspace == Path(profile['workspace']).resolve():
        raise ValueError('Execution requires an isolated workspace')
    if profile.get('environment_fingerprint') and profile['environment_fingerprint'] != _environment_fingerprint():
        raise ValueError('Native environment changed since baseline capture')
    _, current_hashes = _configuration(profile['runner'], Path(profile['workspace']))
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
        # Native configuration is copied, not rewritten or stripped of hooks/plugins/MCP.
        native_directories = [('.claude', 'CLAUDE_CONFIG_DIR')] if runner == 'claude' else [('.codex', 'CODEX_HOME'), ('.agents', None)]
        for directory, override in native_directories:
            source = Path(env.get(override, Path.home() / directory)) if override else Path.home() / directory
            if source.is_dir():
                shutil.copytree(source, isolated / directory, ignore=shutil.ignore_patterns(*_NATIVE_IGNORES), symlinks=False)
            (isolated / directory).mkdir(parents=True, exist_ok=True)
            if override:
                env[override] = str(isolated / directory)
        if runner == 'claude' and (Path.home() / '.claude.json').is_file():
            shutil.copy2(Path.home() / '.claude.json', isolated / '.claude.json')
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
        if runner == 'claude':
            command = [binary, '-p', '--output-format', 'json', *args]
            if profile.get('model'):
                command += ['--model', profile['model']]
            if profile.get('effort'):
                command += ['--effort', profile['effort']]
            if gateway_url:
                env.update(ANTHROPIC_BASE_URL=gateway_url, ANTHROPIC_API_KEY=gateway_key, ANTHROPIC_AUTH_TOKEN=gateway_key)
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
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError('Native configuration preparation exhausted the time limit')
        proc = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        status = 'completed'
        try:
            stdout, stderr = proc.communicate(prefix + prompt, timeout=remaining)
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
