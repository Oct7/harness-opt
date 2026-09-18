"""Start-hook recommendation. Never changes the live model."""
import json
import os
from pathlib import Path

from .calibrate import read_routing
from .classify import classify

ORDER = ('low', 'medium', 'high', 'xhigh', 'ultra', 'max')


def _rank(effort):
    return ORDER.index(effort) if effort in ORDER else -1


def _pick(row, host, workspace):
    overrides = row.get('workspace_overrides') or {}
    key = str(Path(workspace).resolve()) if workspace else ''
    if key in overrides:
        return overrides[key], 'override', host == 'cursor'
    rec = row.get('recommended')
    if isinstance(rec, dict) and rec.get('model'):
        return rec, 'recommended', host == 'cursor' or rec.get('runner') != host
    observed = (row.get('observed') or {}).get(host)
    if isinstance(observed, dict) and observed.get('model'):
        return observed, 'observed', True
    return None, 'none', True


def route(prompt, host, current_model, current_effort, workspace, state_dir):
    task_class = classify(prompt)
    empty = {'ask': False, 'message': '', 'class': task_class, 'source': 'none',
             'recommended': None, 'unverified': True}
    if task_class == 'mixed_or_unclear':
        return empty
    data = read_routing(state_dir)
    row = (data.get('classes') or {}).get(task_class) or {}
    picked, source, unverified = _pick(row, host, workspace)
    if not picked:
        return empty
    rec_effort = picked.get('effort')
    ask = _rank(current_effort) > _rank(rec_effort)
    recommended = {'model': picked.get('model'), 'effort': rec_effort}
    if not ask:
        return {**empty, 'class': task_class, 'source': source, 'recommended': recommended, 'unverified': unverified}
    message = f"지금 {current_model} {current_effort}. 과거 {task_class}는 {picked.get('model')} {rec_effort}. 바꿀까요?"
    if unverified:
        message += ' unverified'
    result = {'ask': True, 'message': message, 'class': task_class, 'source': source,
              'recommended': recommended, 'unverified': unverified}
    path = Path(state_dir) / 'model-routing' / 'outcomes.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + '\n')
    os.chmod(path, 0o600)
    return result
