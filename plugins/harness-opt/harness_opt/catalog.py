"""Local skill inventory and observed invocation signals; never deletes anything."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote


def _walk(root):
    seen = set()
    for directory, dirs, files in os.walk(root, followlinks=True):
        real = Path(directory).resolve()
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        dirs[:] = sorted(d for d in dirs if d not in {'.git', 'node_modules', '.venv', 'tests', 'fixtures', 'examples'})
        yield Path(directory), files


def _timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) if isinstance(value, str) and ('+' in value or value.endswith('Z')) else None
    except ValueError:
        return None


def _invocations(event):
    """Count explicit requests/tool invocations, never advertised skill catalogs."""
    payload = event.get('payload', {})
    message = event.get('message', {})
    text = ''
    if event.get('type') == 'event_msg' and isinstance(payload, dict) and payload.get('type') == 'user_message':
        text = payload.get('message', '')
    elif event.get('type') == 'response_item' and isinstance(payload, dict) and payload.get('type') == 'message' and payload.get('role') == 'user':
        content = payload.get('content', [])
        text = '\n'.join(c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'input_text') if isinstance(content, list) else ''
    elif event.get('type') == 'user' and isinstance(message, dict):
        content = message.get('content', '')
        text = content if isinstance(content, str) else '\n'.join(c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text') if isinstance(content, list) else ''
    elif event.get('type') == 'assistant' and isinstance(message, dict):
        content = message.get('content', [])
        if isinstance(content, list):
            return {c['input']['skill'] for c in content if isinstance(c, dict) and c.get('type') == 'tool_use' and c.get('name') == 'Skill' and isinstance(c.get('input'), dict) and isinstance(c['input'].get('skill'), str)}
    elif event.get('is_bash') is True:
        return set()
    elif isinstance(event.get('prompt'), str):
        text = event['prompt']
    if not isinstance(text, str):
        return set()
    # ponytail: explicit invocation signals only; add native event adapters for implicit usage.
    return set(re.findall(r'(?m)^\s*[$/]([\w-]+(?::[\w-]+)*)\b', text)) | set(re.findall(r'<command-name>/?([\w:-]+)</command-name>', text))


def catalog(scope, runner, workspace, view='all', days=90):
    workspace = Path(workspace).resolve()
    if view == 'classes' and scope != 'project':
        raise ValueError('Class catalog is workspace-local; use --scope project')
    if view == 'classes':
        from .classify import class_summary, load_workspace_turns
        rows, coverage = load_workspace_turns(runner, workspace, days)
        return dict(scope=scope, runner=runner, view=view, skills=[], classes=class_summary(rows),
                    suggestions=[], coverage=dict(days=days, **coverage),
                    limitations='Counts are sessions with a real user prompt of that class, not complete usage.')
    if runner == 'codex':
        native = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        roots = [native / 'skills', native / 'plugins/cache', Path.home() / '.agents/skills']
    elif runner == 'grok':
        native = Path(os.environ.get('GROK_HOME', Path.home() / '.grok'))
        roots = [native / 'skills', native / 'installed-plugins', native / 'plugins']
    else:
        native = Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude'))
        roots = [native / 'skills', native / 'plugins/cache']
    if scope == 'project':
        if runner == 'codex':
            roots = [workspace / '.agents/skills', workspace / '.codex/skills']
        elif runner == 'grok':
            roots = [workspace / '.grok/skills', workspace / '.agents/skills']
        else:
            roots = [workspace / '.claude/skills']
        roots += [workspace / 'plugins']
    rows = {}
    for root in roots:
        for directory, files in _walk(root):
            if 'SKILL.md' not in files:
                continue
            path = (directory / 'SKILL.md').resolve()
            if path in rows:
                continue
            content = path.read_text(errors='replace')
            match = re.search(r'^name:\s*[\"\']?([\w-]+)', content, re.M)
            name = match.group(1) if match else directory.name
            plugin = None
            plugin_path = None
            for parent in directory.parents:
                manifest = next((parent / d / 'plugin.json' for d in ('.codex-plugin', '.claude-plugin', '.grok-plugin') if (parent / d / 'plugin.json').is_file()), None)
                if manifest:
                    try:
                        plugin = json.loads(manifest.read_text()).get('name')
                        plugin_path = str(parent.resolve())
                    except (ValueError, OSError):
                        pass
                    break
                if parent == root:
                    break
            if name == 'harness-opt' or plugin == 'harness-opt':
                continue
            rows[path] = dict(name=name, path=str(path.parent), plugin=plugin, plugin_path=plugin_path, count=0, last_used=None)
    aliases = defaultdict(list)
    for row in rows.values():
        aliases[row['name']].append(row)
        if row['plugin']:
            aliases[row['plugin'] + ':' + row['name']].append(row)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    history = native / ('projects' if runner == 'claude' else 'sessions')
    scanned = malformed = ambiguous = 0
    first = last = None
    for directory, files in _walk(history):
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            try:
                with (directory / name).open(errors='replace') as stream:
                    session_cwd = None
                    observed = set()
                    for line in stream:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            malformed += 1
                            continue
                        if not isinstance(event, dict):
                            continue
                        if event.get('type') == 'session_meta' and isinstance(event.get('payload'), dict):
                            session_cwd = event['payload'].get('cwd')
                        cwd = event.get('cwd', session_cwd)
                        if not cwd and runner == 'grok':
                            decoded = unquote(Path(directory).name)
                            if decoded.startswith('/'):
                                cwd = decoded
                        if scope == 'project' and (not isinstance(cwd, str) or Path(cwd).resolve() != workspace):
                            continue
                        stamp = _timestamp(event.get('timestamp'))
                        if not stamp or stamp < cutoff:
                            continue
                        scanned += 1
                        first = min(first, stamp) if first else stamp
                        last = max(last, stamp) if last else stamp
                        for invocation in _invocations(event):
                            matches = aliases.get(invocation, [])
                            if len(matches) > 1:
                                ambiguous += 1
                                continue
                            if len(matches) != 1:
                                continue
                            row = matches[0]
                            # One observation per skill/session avoids request + tool double counts.
                            if row['path'] not in observed:
                                row['count'] += 1
                                observed.add(row['path'])
                            iso = stamp.isoformat()
                            row['last_used'] = max(row['last_used'] or iso, iso)
            except OSError:
                malformed += 1
    suggestions = []
    for row in rows.values():
        if row['count']:
            suggestions.append(dict(kind='skill', path=row['path'], action='consider_improvement', reason=f"Observed in {row['count']} sessions; last {row['last_used']}"))
        elif scanned:
            suggestions.append(dict(kind='skill', path=row['path'], action='review_removal', reason=f'No unambiguous invocation observed in the last {days} days; usage may be missing.'))
    groups = defaultdict(list)
    for row in rows.values():
        if row['plugin_path']:
            groups[row['plugin_path']].append(row)
    for path, skills in groups.items():
        if scanned and not any(row['count'] for row in skills):
            suggestions.append(dict(kind='plugin', path=path, action='review_removal', reason='No skill invocations observed; verify installation, hooks, MCP, dependencies and other capabilities before removal.'))
    result = sorted(rows.values(), key=lambda r: (r['name'], r['path']))
    if view in ('frequent', 'recent'):
        result = sorted((r for r in result if r['count']), key=lambda r: (r['count'], r['last_used']) if view == 'frequent' else (r['last_used'], r['count']), reverse=True)
    return dict(scope=scope, runner=runner, view=view, skills=result, suggestions=suggestions,
                coverage=dict(days=days, events=scanned, first=first, last=last, malformed_or_unreadable=malformed, ambiguous=ambiguous),
                limitations='Counts are sessions with explicit invocation signals, not complete usage. Cached plugin versions may be inactive. No observations means unknown, not unused. No files are deleted.')
