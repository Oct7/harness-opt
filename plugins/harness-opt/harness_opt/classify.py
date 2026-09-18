"""Deterministic task-class labels and historical case picks. No model calls."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote

from .evaluation import validate_cases


CLASSES = (
    'debug_investigate', 'implement_feature', 'ui_tweak', 'ui_redesign',
    'architecture_greenfield', 'review_audit', 'research_docs', 'harness_plugin',
    'content_oneshot', 'git_deploy_ops', 'multi_system_incident', 'mixed_or_unclear',
)
BLOCKED = frozenset({'git_deploy_ops', 'mixed_or_unclear'})
CLASS_EFFORT = {
    'git_deploy_ops': 'low', 'content_oneshot': 'low', 'ui_tweak': 'low',
    'implement_feature': 'medium', 'harness_plugin': 'medium', 'research_docs': 'medium',
    'debug_investigate': 'high', 'ui_redesign': 'high', 'review_audit': 'high',
    'architecture_greenfield': 'xhigh', 'multi_system_incident': 'xhigh',
}


def effort_cap(name):
    return CLASS_EFFORT.get(name)
NOISE_PREFIXES = (
    '# AGENTS.md', '# Files mentioned', '<environment_context>', '<skill>',
    '<recommended_plugins>', '<user_instructions>', '<INSTRUCTIONS>',
    '<skills_instructions>', '<multi_agent', '<permissions',
)
RETRY = re.compile(r'고치|안 됨|안되|실패|아직도|또 |다시 |error|failed', re.I)
MUTATING = re.compile(
    r'(?i)^(전체 )?git pull\.?$|^푸시 배포|^배포해\b|^(please )?(commit|push|deploy)\b')
SUCCESS = re.compile(r'(?m)^(?:성공|완료|해야|되도록|되게|so that |must |should ).+')


def is_noise(text):
    s = (text or '').lstrip()
    return (not s) or s.startswith(NOISE_PREFIXES) or (s.startswith('<') and 'user_query' not in s[:200] and len(s) > 300)


def is_mutating(text):
    s = (text or '').strip()
    return classify(s) == 'git_deploy_ops' or bool(MUTATING.search(s) and len(s) < 80)


def classify(text):
    t = text or ''
    if re.search(r'(?i)nightly|canary|\bci\b|돈 ?잡', t) and len(re.findall(r'(?i)실패|fail|red|오류|에러', t)) >= 2:
        return 'multi_system_incident'
    if re.search(r'(?i)git pull|푸시 배포|\bcommit\b|\bpush\b|배포해|\bdeploy\b', t) and len(t) < 120:
        return 'git_deploy_ops'
    rules = (
        ('ui_redesign', r'(?i)클론|glass|리디자인|완전히 개선|디자인 시스템|krea|figma'),
        ('ui_tweak', r'너비|default|명칭|이름만|폰트|탭이'),
        ('review_audit', r'(?i)리뷰|\breview\b|전수|점검해서 리스트'),
        ('harness_plugin', r'(?i)harness-opt|\bhook\b|토큰미터'),
        ('architecture_greenfield', r'아이디어|아키텍처|/goal|메타버스|신규 구현'),
        ('research_docs', r'(?i)조사|pricing|방안 제안|테스트방법'),
        ('debug_investigate', r'(?i)버그|에러|오류|안 됨|안되|실패|고쳐|\bfix\b|debug|재현|원인|문제|딜레이|느려|파악|누출|준비중'),
        ('implement_feature', r'(?i)추가|구현|만들어|기능|\badd\b|implement|자동입력'),
        ('content_oneshot', r'번역|답장란'),
    )
    for name, pattern in rules:
        if re.search(pattern, t):
            return name
    return 'mixed_or_unclear'


def kind_for(prompt, later=(), failed=False):
    if failed or any(RETRY.search(x or '') for x in later):
        return 'failure'
    if len(prompt or '') < 80:
        return 'boundary'
    if (prompt or '').count('.') + (prompt or '').count('?') + (prompt or '').count('。') <= 1:
        if not re.search(r'[/\\]\w|\.\w{1,5}\b|오류|에러|error|실패', prompt or '', re.I):
            return 'boundary'
    return 'normal'


def criteria_for(prompt):
    found = [m.group(0).strip() for m in SUCCESS.finditer(prompt or '') if m.group(0).strip()]
    return found or ['Satisfy the user request as written.', prompt]


def select_cases(rows, task_class):
    if task_class not in CLASSES or task_class in BLOCKED:
        raise ValueError(f'{task_class} is not calibratable')
    usable = []
    for row in rows:
        prompt = row['prompt']
        if is_noise(prompt) or classify(prompt) != task_class or is_mutating(prompt):
            continue
        usable.append(dict(row, kind=kind_for(prompt, row.get('later') or [], row.get('failed', False))))
    buckets = {'normal': [], 'boundary': [], 'failure': []}
    for row in sorted(usable, key=lambda item: item['stamp'], reverse=True):
        buckets[row['kind']].append(row)
    if len(buckets['normal']) < 2 or len(buckets['boundary']) < 1 or len(buckets['failure']) < 1:
        raise ValueError('fewer than four assignable cases after exclusions')
    chosen = buckets['normal'][:2] + buckets['boundary'][:1] + buckets['failure'][:1]
    chosen.sort(key=lambda item: item['stamp'])
    payload = []
    for row in chosen:
        payload.append(dict(kind=row['kind'], prompt=row['prompt'], criteria=criteria_for(row['prompt']),
                            files=row.get('files') or {}, required_files=[], file_contains={}))
    return validate_cases({'cases': payload}, 4)


def class_summary(rows):
    sessions = defaultdict(set)
    last = {}
    for row in rows:
        name = classify(row['prompt'])
        sessions[name].add(row.get('session'))
        last[name] = max(last.get(name, ''), row.get('stamp') or '')
    result = []
    for name in CLASSES:
        if not sessions.get(name):
            continue
        calibratable = False
        if name not in BLOCKED:
            try:
                select_cases(rows, name)
                calibratable = True
            except ValueError:
                pass
        result.append(dict(name=name, count=len(sessions[name]), last_seen=last[name], calibratable=calibratable))
    return result


def _timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) if isinstance(value, str) and ('+' in value or value.endswith('Z')) else None
    except ValueError:
        return None


def _walk(root):
    seen = set()
    for directory, dirs, files in os.walk(root, followlinks=True):
        real = Path(directory).resolve()
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        dirs[:] = sorted(d for d in dirs if d not in {'.git', 'node_modules', '.venv'})
        yield Path(directory), files


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') in ('text', 'input_text'))
    return ''


def _user_text(event, runner):
    payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
    if event.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
        return _content_text(payload.get('content'))
    if event.get('type') == 'event_msg' and payload.get('type') == 'user_message':
        return payload.get('message') or ''
    if event.get('type') == 'user':
        message = event.get('message') or {}
        text = _content_text(message.get('content'))
        if text.startswith('Caveat:') or '<command-name>' in text[:100]:
            return ''
        return text
    if runner == 'grok' and isinstance(event.get('prompt'), str) and event.get('is_bash') is not True:
        return event['prompt']
    return ''


def load_workspace_turns(runner, workspace, days=90):
    return load_turns(runner, days, Path(workspace).resolve())


def load_turns(runner, days=90, workspace=None):
    workspace = Path(workspace).resolve() if workspace is not None else None
    if runner == 'codex':
        native = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        history = native / 'sessions'
    elif runner == 'grok':
        native = Path(os.environ.get('GROK_HOME', Path.home() / '.grok'))
        history = native / 'sessions'
    else:
        native = Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude'))
        history = native / 'projects'
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sessions = {}
    scanned = malformed = 0
    first = last = None
    for directory, files in _walk(history):
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            session_id = str(directory / name)
            try:
                session_cwd = None
                turns = []
                with (directory / name).open(errors='replace') as stream:
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
                        if workspace is not None and (not isinstance(cwd, str) or Path(cwd).resolve() != workspace):
                            continue
                        stamp = _timestamp(event.get('timestamp'))
                        if not stamp and isinstance(event.get('payload'), dict):
                            stamp = _timestamp(event['payload'].get('timestamp'))
                        text = _user_text(event, runner)
                        if is_noise(text) or not text.strip():
                            continue
                        if not stamp or stamp < cutoff:
                            continue
                        scanned += 1
                        first = min(first, stamp) if first else stamp
                        last = max(last, stamp) if last else stamp
                        failed = event.get('type') in ('error',) or (isinstance(event.get('payload'), dict) and event['payload'].get('status') in ('failed', 'error'))
                        turns.append(dict(text=text, stamp=stamp.isoformat(), failed=failed))
                if turns:
                    sessions[session_id] = turns
            except OSError:
                malformed += 1
    rows = []
    for session_id, turns in sessions.items():
        for i, turn in enumerate(turns):
            later = [item['text'] for item in turns[i + 1:]]
            rows.append(dict(prompt=turn['text'], stamp=turn['stamp'], later=later,
                             failed=turn['failed'] or any(item['failed'] for item in turns[i + 1:]),
                             session=session_id, files={}))
    return rows, dict(events=scanned, first=first, last=last, malformed_or_unreadable=malformed)
