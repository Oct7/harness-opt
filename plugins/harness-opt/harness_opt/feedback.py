"""End-of-work feedback. Records only; does not change the live model."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .calibrate import read_routing, routing_path
from .classify import CLASSES
from .optimizer import _atomic_text


def record_feedback(state_dir, task_class, host, model, effort, verdict):
    if task_class not in CLASSES or task_class == 'mixed_or_unclear':
        return {'status': 'skipped'}
    if verdict not in ('good', 'bad') or not model or not effort or not host:
        return {'status': 'skipped'}
    data = read_routing(state_dir)
    data['schema_version'] = max(int(data.get('schema_version') or 1), 2)
    row = data.setdefault('classes', {}).setdefault(task_class, {
        'observed': {}, 'recommended': None, 'ceiling': None,
        'workspace_overrides': {}, 'evidence': [], 'feedback': []})
    row.setdefault('feedback', []).append({
        'host': host, 'model': model, 'effort': effort, 'verdict': verdict,
        'stamp': datetime.now(timezone.utc).isoformat()})
    path = routing_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(path, 0o600)
    return {'status': 'ok'}


def ask_feedback(prompt, host, model, effort):
    from .classify import classify
    task_class = classify(prompt or '')
    if not model or not effort or task_class == 'mixed_or_unclear':
        return {'status': 'skipped', 'message': ''}
    return {
        'status': 'ask',
        'class': task_class,
        'message': f'이번 작업({task_class})에 {model} {effort}. good / bad',
    }
