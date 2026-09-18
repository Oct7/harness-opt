"""Observational class routing report. No model calls, no invented IDs."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .calibrate import _below_ceiling, read_routing, routing_path
from .classify import CLASS_EFFORT, class_summary, effort_cap, load_turns
from .optimizer import _atomic_text
from .runner import catalog_fingerprint, disk_ceiling, native_models


def _shift(listed, effort, step):
    if effort not in listed:
        return None
    index = listed.index(effort) + step
    if 0 <= index < len(listed):
        return listed[index]
    return listed[0] if step < 0 else listed[-1]


def pick_observed(task_class, models, ceiling_model, ceiling_effort, feedback=None):
    cap = effort_cap(task_class)
    if not cap or not models:
        return None
    by_id = {m['id']: m.get('efforts') or [] for m in models if m.get('id')}

    def clip(model_id, wanted):
        listed = by_id.get(model_id) or []
        allowed = _below_ceiling(listed, ceiling_effort)
        if not allowed:
            return None
        if wanted in allowed:
            return wanted
        return allowed[-1]

    if isinstance(feedback, dict) and feedback.get('verdict') in ('good', 'bad'):
        model_id = feedback.get('model')
        effort = feedback.get('effort')
        listed = by_id.get(model_id) or []
        if model_id in by_id and effort in listed:
            if feedback['verdict'] == 'bad':
                effort = _shift(listed, effort, 1)
            effort = clip(model_id, effort)
            if effort:
                return {'model': model_id, 'effort': effort}

    if ceiling_model in by_id:
        effort = clip(ceiling_model, cap)
        if effort:
            return {'model': ceiling_model, 'effort': effort}
    for model in models:
        effort = clip(model['id'], cap)
        if effort:
            return {'model': model['id'], 'effort': effort}
    return None


def is_stale(data, fingerprints, now=None):
    now = now or datetime.now(timezone.utc)
    stored = data.get('catalog_fingerprint') or {}
    if any(stored.get(host) != fingerprints.get(host) for host in fingerprints):
        return True
    raw = data.get('catalog_cutoff') or ''
    try:
        cut = datetime.fromisoformat(raw).date()
    except ValueError:
        return True
    return (now.date() - cut).days >= 30


def _latest_feedback(row, host):
    items = [item for item in (row.get('feedback') or []) if item.get('host') == host]
    if not items:
        items = [item for item in (row.get('feedback') or []) if not item.get('host')]
    return items[-1] if items else None


def _markdown(data, coverage, stale, summary=None):
    lines = ['# Class route report', '', f"cutoff: {data.get('catalog_cutoff', '')}",
             f"stale: {stale}", '']
    summary = summary or {}
    for name, row in (data.get('classes') or {}).items():
        observed = row.get('observed') or {}
        rec = row.get('recommended')
        stats = summary.get(name) or {}
        lines.append(f"## {name}")
        lines.append(f"- observed: {json.dumps(observed, ensure_ascii=False)}")
        if rec:
            lines.append(f"- verified: {rec.get('model')} {rec.get('effort')}")
        if stats.get('count'):
            lines.append(f"- sessions: {stats['count']} last={stats.get('last_seen', '')} calibratable={stats.get('calibratable')}")
        lines.append('')
    ceilings = data.get('disk_ceiling') or {}
    if ceilings:
        lines.append(f"ceiling: {json.dumps(ceilings, ensure_ascii=False)}")
        lines.append('')
    if coverage:
        lines.append(f"events: {coverage.get('events', 0)}")
    return '\n'.join(lines) + '\n'


def report(runner, state_dir, days=90, hosts=None, catalogs=None, ceilings=None, turns=None):
    state_dir = Path(state_dir)
    hosts = tuple(hosts or (runner,))
    catalogs = catalogs or {}
    ceilings = ceilings or {}
    if turns is None:
        sources = ('claude', 'codex', 'grok') if runner == 'cursor' else (runner,)
        turns = []
        for source in sources:
            rows, _ = load_turns(source, days, workspace=None)
            turns.extend(rows)
    data = read_routing(state_dir)
    data['schema_version'] = max(int(data.get('schema_version') or 1), 2)
    data['catalog_cutoff'] = datetime.now(timezone.utc).date().isoformat()
    fingerprints = dict(data.get('catalog_fingerprint') or {})
    used_ceilings = dict(data.get('disk_ceiling') or {})
    summary = {item['name']: item for item in class_summary(turns)}
    names = list(dict.fromkeys([*summary, *CLASS_EFFORT, *(data.get('classes') or {})]))
    for host in hosts:
        models = native_models(host, {'catalog': catalogs[host]} if host in catalogs else {})
        fingerprints[host] = catalog_fingerprint(models)
        ceiling = ceilings.get(host) or disk_ceiling(host)
        if ceiling:
            used_ceilings[host] = ceiling
        ceiling_model, ceiling_effort = ceiling.get('model'), ceiling.get('effort')
        for name in names:
            if name == 'mixed_or_unclear':
                continue
            row = data.setdefault('classes', {}).setdefault(name, {
                'observed': {}, 'recommended': None, 'ceiling': None,
                'workspace_overrides': {}, 'evidence': [], 'feedback': []})
            picked = pick_observed(name, models, ceiling_model, ceiling_effort, _latest_feedback(row, host))
            observed = row.setdefault('observed', {})
            if picked:
                observed[host] = picked
            else:
                observed.pop(host, None)
    data['catalog_fingerprint'] = fingerprints
    if used_ceilings:
        data['disk_ceiling'] = used_ceilings
    path = routing_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(path, 0o600)
    coverage = {'events': len(turns)}
    markdown_path = path.parent / 'REPORT.md'
    stale = is_stale(data, fingerprints)
    _atomic_text(markdown_path, _markdown(data, coverage, stale, summary))
    os.chmod(markdown_path, 0o600)
    empty = not turns
    return {'status': 'ok', 'path': str(path), 'markdown_path': str(markdown_path),
            'classes': data.get('classes'), 'stale': stale,
            'catalog_fingerprint': fingerprints,
            **({'reason': 'empty'} if empty else {})}
