"""Install harness-opt start/end hooks without touching other entries."""
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from .optimizer import _atomic_text


def _cli(action, host):
    binary = shutil.which('harness-opt')
    prefix = shlex.quote(binary) if binary else f'{shlex.quote(sys.executable)} -m harness_opt'
    return f'{prefix} {action} --host {host} --hook-stdin'


def _ours(command, needle):
    return isinstance(command, str) and needle in command


def _merge(existing, command, needle):
    kept = [item for item in existing if not _ours(item.get('command'), needle)]
    kept.append({'command': command})
    return kept


def _nested_merge(existing, command, needle):
    kept = []
    for group in existing or []:
        if not isinstance(group, dict):
            kept.append(group)
            continue
        hooks = [item for item in (group.get('hooks') or [])
                 if not (isinstance(item, dict) and _ours(item.get('command'), needle))]
        extra = {key: value for key, value in group.items() if key != 'hooks'}
        if hooks:
            kept.append({**extra, 'hooks': hooks})
        elif extra:
            kept.append(extra)
    kept.append({'hooks': [{'type': 'command', 'command': command}]})
    return kept


def _load(path):
    data = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except ValueError:
            pass
    return data


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    if path.exists():
        os.chmod(path, path.stat().st_mode | 0o600)


def _install_flat(path, host):
    data = _load(path)
    if path.is_file() and not data:
        data = {'version': 1, 'hooks': {}}
    data.setdefault('version', 1)
    hooks = dict(data.get('hooks') or {})
    hooks['beforeSubmitPrompt'] = _merge(
        hooks.get('beforeSubmitPrompt') or [], _cli('route', host), f'route --host {host}')
    hooks['sessionEnd'] = _merge(
        hooks.get('sessionEnd') or [], _cli('feedback', host), f'feedback --host {host}')
    data['hooks'] = hooks
    _write(path, data)
    return str(path)


def _install_nested(path, host, start='UserPromptSubmit', end='Stop'):
    data = _load(path)
    hooks = dict(data.get('hooks') or {})
    hooks[start] = _nested_merge(hooks.get(start) or [], _cli('route', host), f'route --host {host}')
    hooks[end] = _nested_merge(hooks.get(end) or [], _cli('feedback', host), f'feedback --host {host}')
    data['hooks'] = hooks
    _write(path, data)
    return str(path)


def _install_owned(directory, host):
    path = Path(directory) / 'harness-opt.json'
    _write(path, {'hooks': {
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': _cli('route', host)}]}],
        'Stop': [{'hooks': [{'type': 'command', 'command': _cli('feedback', host)}]}],
    }})
    return str(path)


def install_hooks(cursor_hooks, plugin_hooks=None, claude_settings=None, codex_hooks=None,
                  grok_hooks=None):
    paths = [_install_flat(Path(cursor_hooks), 'cursor')]
    if claude_settings:
        paths.append(_install_nested(Path(claude_settings), 'claude'))
    if codex_hooks:
        paths.append(_install_nested(Path(codex_hooks), 'codex'))
    if grok_hooks:
        paths.append(_install_owned(Path(grok_hooks), 'grok'))
    return {'status': 'ok', 'path': paths[0], 'paths': paths}
