"""Replay historical class cases; write model/effort only. Does not call optimize()."""
import json
import os
import time
import uuid
from pathlib import Path

from .budget import Budget, BudgetExceeded
from .classify import BLOCKED, CLASSES, load_workspace_turns, select_cases
from .evaluation import direct_checks, judge_prompt, materialize, semantic_result
from .gateway import Gateway
from .optimizer import (
    _atomic_text, _evidence, _hashes, _native_text, _redact_value, _stable_model,
    _success, _usage_totals, _validate_execution, _write_report,
)
from .providers import discover_models, load_providers
from .runner import WorkspaceSnapshot, capture_profile, execute, native_models
from .store import Store, fingerprint

ROUTING_CUTOFF = '2026-09-18'


def routing_path(state_dir):
    return Path(state_dir) / 'model-routing' / 'routing.json'


def read_routing(state_dir):
    path = routing_path(state_dir)
    if not path.is_file():
        return {'schema_version': 1, 'catalog_cutoff': ROUTING_CUTOFF, 'classes': {}}
    return json.loads(path.read_text())


def _beats(new, old):
    compared = []
    for key in ('mean_duration', 'mean_total_tokens', 'mean_cost_usd'):
        left, right = new.get(key), old.get(key)
        if left is None or right is None:
            continue
        if left < right:
            compared.append(True)
        elif left > right:
            compared.append(False)
    return bool(compared) and all(compared)


def write_routing(state_dir, task_class, workspace, winner, ceiling, evidence):
    path = routing_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = read_routing(state_dir)
    data['schema_version'] = max(int(data.get('schema_version') or 1), 2)
    row = data.setdefault('classes', {}).setdefault(task_class, {
        'recommended': None, 'ceiling': ceiling, 'workspace_overrides': {}, 'evidence': [],
        'observed': {}, 'feedback': []})
    row.setdefault('workspace_overrides', {})
    row.setdefault('evidence', [])
    row.setdefault('observed', {})
    row.setdefault('feedback', [])
    row['ceiling'] = ceiling
    row['workspace_overrides'][str(Path(workspace).resolve())] = winner
    previous = row.get('recommended')
    prior = next((item for item in reversed(row['evidence']) if item.get('winner') == previous), None)
    row['evidence'].append(evidence)
    if not previous:
        row['recommended'] = winner
    elif prior and _beats(evidence, prior):
        row['recommended'] = winner
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(path, 0o600)
    return path


def _below_ceiling(listed, ceiling_effort):
    if not listed:
        return []
    if ceiling_effort in listed:
        return [item for item in listed if listed.index(item) <= listed.index(ceiling_effort)]
    return []


def candidate_pairs(runner, execution, profile, models, ceiling_model, ceiling_effort, explicit_effort=None):
    if execution == 'current':
        if 'catalog' in (profile or {}) or runner == 'grok':
            listed = native_models(runner, dict(profile, measurement=(runner == 'cursor')))
        else:
            listed = []
        if not listed:
            efforts = [item for item in (profile.get('efforts') or []) if item]
            if not efforts and ceiling_effort:
                efforts = [ceiling_effort]
            listed = [{'id': ceiling_model or 'native-default', 'provider': 'native', 'efforts': efforts}]
        pairs = []
        for model in listed:
            allowed = _below_ceiling(model.get('efforts') or [], ceiling_effort)
            for item in allowed:
                if model.get('id') == ceiling_model and item == ceiling_effort:
                    continue
                pairs.append((model, item))
        if not pairs:
            raise ValueError('no candidate below ceiling; use --execution api')
        return pairs
    pairs = []
    for model in models:
        if any(model.get(key) is None for key in ('input_per_million', 'output_per_million', 'context_window')):
            continue
        listed = model.get('efforts') or []
        allowed = _below_ceiling(listed, ceiling_effort) if listed else ([explicit_effort] if explicit_effort else [])
        for item in allowed:
            if model.get('id') == ceiling_model and item == ceiling_effort:
                continue
            pairs.append((model, item))
    return pairs


def calibrate(task_class, runner, budget_usd, time_limit, state_dir, env_file,
              workspace=None, baseline_model=None, baseline_provider=None, effort=None,
              force=False, resume=None, repeats=3, execution='current', native_home=None):
    _validate_execution(execution, budget_usd)
    if runner == 'cursor':
        raise ValueError('--runner cursor')
    if runner not in ('claude', 'codex', 'grok'):
        raise ValueError('Runner must be claude, codex, or grok')
    if task_class not in CLASSES or task_class in BLOCKED:
        raise ValueError(f'{task_class} is not calibratable')
    if execution == 'api' and runner == 'grok':
        raise ValueError('Grok has no metered API-gateway adapter; use --execution current')
    if execution == 'current' and baseline_provider:
        raise ValueError('Provider comparisons require --execution api')
    workspace = Path(workspace or Path.cwd()).resolve()
    state_dir = Path(state_dir).resolve()
    if state_dir.is_relative_to(workspace):
        raise ValueError('State directory must stay outside the workspace')
    rows, _ = load_workspace_turns(runner, workspace)
    case_set = select_cases(rows, task_class)
    native_home = Path(native_home).expanduser().resolve() if native_home else None
    profile = capture_profile(runner, workspace, model=baseline_model, effort=effort,
                              current=execution == 'current', native_home=native_home)
    if profile.get('requires_external_fixture') and not profile.get('external_isolation_verified'):
        raise ValueError('Native hooks/MCP require an independently isolated external fixture before optimization. '
                         'Run harness-opt isolate --runner ' + runner + ' then retry with --native-home <destination>')
    ceiling_model = profile.get('model')
    ceiling_effort = profile.get('effort')
    providers, models = {}, []
    if execution == 'api':
        providers = load_providers(env_file)
        if baseline_provider is None and len(providers) == 1:
            baseline_provider = next(iter(providers))
        if baseline_provider not in providers:
            raise ValueError('Specify a configured baseline provider')
        for provider in providers.values():
            models.extend(discover_models(provider))
        baseline = next((item for item in models if item['id'] == ceiling_model and item['provider'] == baseline_provider), None)
        if baseline is None:
            raise ValueError('Baseline model must match the captured native configuration and a discovered model')
    else:
        baseline = {'id': ceiling_model or 'native-default', 'provider': 'native',
                    'efforts': [ceiling_effort] if ceiling_effort else []}
        if runner == 'grok':
            models = native_models(runner, profile)
    pairs = candidate_pairs(runner, execution, profile, models, ceiling_model, ceiling_effort, effort)
    run_id = resume or uuid.uuid4().hex[:12]
    if '/' in run_id or '\\' in run_id or run_id in {'.', '..'}:
        raise ValueError('Invalid run ID')
    directory = state_dir / run_id
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    store = Store(state_dir / 'history.sqlite3')
    budget = Budget(budget_usd, time_limit, on_change=lambda state: store.put('budget', run_id, state))
    started = time.monotonic()
    report = {'id': run_id, 'status': 'no_verified_improvement', 'trials': [], 'reasons': [],
              'recommendations': [], 'provisional_candidates': [], 'mode': 'cost' if execution == 'api' else 'speed',
              'confirmation_repeats': repeats, 'execution': execution, 'cost_savings_verified': False,
              'class': task_class, 'scope': 'recorded environment and historical class cases only'}
    snapshot = WorkspaceSnapshot(workspace, directory / ('snapshot-' + uuid.uuid4().hex[:8]))
    identity = fingerprint({'execution': execution, 'workspace': snapshot.fingerprint, 'class': task_class,
                            'profile': profile, 'cases': [case['prompt'] for case in case_set],
                            'baseline': _stable_model(baseline)})
    previous = store.get('run', run_id)
    if previous and previous.get('identity') != identity:
        raise ValueError('Resume configuration differs from original run')
    journal = store.get('budget', run_id)
    previous_spend = 0.0
    if journal:
        pending = sum(journal.get('reservations', {}).values())
        previous_spend = journal.get('spent', 0) + pending
        budget.spent = previous_spend
    report.update(identity=identity, profile=profile, baseline=baseline, workspace_fingerprint=snapshot.fingerprint)
    store.put('run', run_id, report)
    report['cases'] = case_set
    report['cases_file'] = str(directory / 'cases.json')
    _atomic_text(directory / 'cases.json', json.dumps({'cases': case_set}, indent=2, ensure_ascii=False))

    def call(prompt, model, work, selected_effort=ceiling_effort, target_path=None):
        if execution == 'api' and not budget.remaining:
            raise BudgetExceeded('Budget reached')
        timeout = budget.start_invocation()
        if execution == 'current':
            selected_model = model.get('id') if isinstance(model, dict) and model.get('id') not in (None, 'native-default') else profile.get('model')
            chosen = profile.get('effort') if selected_effort is None else selected_effort
            active = dict(profile, model=selected_model, effort=chosen, evaluation_only=target_path is None)
            result = execute(active, work, prompt, None, timeout, target=target_path)
            result.update(cost_usd=None, calls=[], compatibility_errors=[])
        else:
            with Gateway(providers[model['provider']], model, budget, effort=selected_effort) as gateway:
                active = dict(profile, model=model['id'], effort=selected_effort,
                              gateway_api_key=gateway.api_key, evaluation_only=target_path is None)
                result = execute(active, work, prompt, gateway.base_url, timeout, target=target_path)
            result.update(cost_usd=gateway.cost, calls=gateway.records, compatibility_errors=gateway.compatibility_errors)
            if gateway.compatibility_errors:
                result['status'] = 'compatibility_failure'
            if not gateway.records:
                result['status'] = 'unverified'
                result['reason'] = 'No metered model calls; native gateway routing was not verified'
        result = _redact_value(result, [item.api_key for item in providers.values()])
        errors = {record.get('error') for record in result['calls'] if record.get('error')}
        if errors:
            result['status'] = next((category + '_failure' for category in ('compatibility', 'authentication', 'transport', 'budget') if category in errors), 'unverified')
        report.setdefault('calls', []).append({'model': model['id'], 'result': result})
        store.put('run', run_id, report)
        _write_report(directory, report)
        if 'budget' in errors:
            raise BudgetExceeded('Gateway could not reserve the next call within the configured budget')
        return result

    def judge(case, base, candidate, swapped):
        work = directory / ('judge-work-' + uuid.uuid4().hex[:8])
        work.mkdir()
        result = call(judge_prompt(case, base, candidate, swapped), baseline, work)
        if not _success(result):
            return {'verdict': 'indeterminate', 'reason': result.get('reason', result['status'])}
        return semantic_result(_native_text(result['output']))

    def trial(name, model, selected_effort, cases, count=1):
        key = fingerprint({'identity': identity, 'model': _stable_model(model), 'effort': selected_effort,
                           'cases': cases, 'repeats': count})
        cached = None if force else store.failure(key, versioned=bool(model.get('model_version')) and not bool(model.get('alias_target')))
        if cached:
            reused = dict(cached, name=name, reused=True)
            report['trials'].append(reused)
            return reused
        record = {'name': name, 'model': _stable_model(model), 'effort': selected_effort, 'changes': {},
                  'status': 'passed', 'runs': [], 'reused': False, 'in_progress': True}
        report['trials'].append(record)
        for case in cases:
            if case.get('unverified_reason') or case['id'] not in baselines:
                record['status'] = 'unverified'
                continue
            for repeat in range(count):
                work = snapshot.restore(directory / ('trial-work-' + uuid.uuid4().hex[:8]))
                materialize(case, work)
                before = _hashes(work)
                result = call(case['prompt'], model, work, selected_effort, Path(profile['workspace']))
                errors = direct_checks(case, work)
                evidence = _evidence(result, work, before, [item.api_key for item in providers.values()])
                judges = []
                if _success(result) and not errors:
                    judges = [judge(case, baselines[case['id']]['evidence'], evidence, False),
                              judge(case, baselines[case['id']]['evidence'], evidence, True)]
                record['runs'].append({'case': case['id'], 'repeat': repeat, 'result': result, 'checks': errors, 'judges': judges})
                if not _success(result):
                    record['status'] = 'unverified'
                elif errors or any(item['verdict'] == 'below' for item in judges):
                    record['status'] = 'quality_failure'
                elif not judges or any(item['verdict'] == 'indeterminate' for item in judges):
                    record['status'] = 'unverified'
                if record['status'] != 'passed':
                    break
            if record['status'] != 'passed':
                break
        runs = record['runs']
        record['mean_duration'] = sum(item['result'].get('duration', 0) for item in runs) / len(runs) if runs else None
        costs = [item['result']['cost_usd'] for item in runs]
        record['mean_cost_usd'] = sum(costs) / len(costs) if costs and all(item is not None for item in costs) else None
        totals = _usage_totals([item['result'] for item in runs])
        record['mean_total_tokens'] = totals['total_tokens'] / len(runs) if totals['total_tokens'] is not None else None
        if record['status'] == 'quality_failure':
            store.put('failure', key, record)
        record['in_progress'] = False
        _write_report(directory, report)
        return record

    baselines = {}
    try:
        for case in case_set:
            work = snapshot.restore(directory / ('baseline-work-' + uuid.uuid4().hex[:8]))
            materialize(case, work)
            before = _hashes(work)
            result = call(case['prompt'], baseline, work, target_path=Path(profile['workspace']))
            errors = direct_checks(case, work)
            if _success(result) and not errors:
                baselines[case['id']] = {'result': result, 'evidence': _evidence(result, work, before, [item.api_key for item in providers.values()])}
            else:
                report.setdefault('baseline_failures', []).append({'case': case['id'], 'result': result, 'checks': errors})
                report['reasons'].append(f'Baseline {case["id"]} failed')
        explore = [case for case in case_set if case['split'] == 'exploration']
        passing = []
        pending = []
        for model, selected in pairs:
            label = selected or 'default'
            record = trial(f'{model["provider"]}/{model["id"]}:{label}', model, selected, explore)
            if record['status'] == 'passed':
                passing.append(record)
        if len(baselines) == len(case_set):
            base_costs = [item['result']['cost_usd'] for item in baselines.values()]
            base_cost = sum(base_costs) / len(base_costs) if all(item is not None for item in base_costs) else None
            base_time = sum(item['result']['duration'] for item in baselines.values()) / len(baselines)
            base_usage = _usage_totals([item['result'] for item in baselines.values()])
            base_tokens = base_usage['total_tokens'] / len(baselines) if base_usage['total_tokens'] is not None else None
            report['baseline_metrics'] = {'mean_duration': base_time, 'mean_cost_usd': base_cost, 'mean_total_tokens': base_tokens}
            for candidate in passing:
                final = trial('confirm:' + candidate['name'], candidate['model'], candidate['effort'], case_set, repeats)
                improvements = []
                elapsed = final['mean_duration']
                if elapsed is not None and elapsed < base_time:
                    improvements.append('completion_time')
                tokens_known = base_tokens is not None and final['mean_total_tokens'] is not None
                if tokens_known and final['mean_total_tokens'] < base_tokens:
                    improvements.append('reported_tokens')
                if execution == 'api':
                    better = base_cost is not None and final['mean_cost_usd'] is not None and final['mean_cost_usd'] < base_cost and 'completion_time' in improvements
                    if better:
                        improvements.append('cost')
                else:
                    better = bool(improvements) and elapsed is not None and elapsed <= base_time and (not tokens_known or final['mean_total_tokens'] <= base_tokens)
                if final['status'] == 'passed' and better:
                    if repeats < 3:
                        final['provisional'] = True
                        report['provisional_candidates'].append({'name': final['name'], 'cost_usd': final['mean_cost_usd'],
                                                               'duration': final['mean_duration'], 'repeats': repeats})
                        continue
                    copy = snapshot.restore(directory / ('approved-' + uuid.uuid4().hex[:8]))
                    replay_profile = dict(profile, model=final['model']['id'], effort=final['effort'])
                    replay = {'execution': execution, 'runner_profile': replay_profile, 'provider': final['model']['provider'],
                              'model': final['model'], 'workspace': str(copy), 'target': str(copy),
                              'verified_scope': report['scope'], 'confirmation_repeats': repeats,
                              'approved_hash': WorkspaceSnapshot(copy, directory / ('integrity-' + uuid.uuid4().hex[:8])).fingerprint}
                    replay_path = directory / f'profile-{len(report["recommendations"]) + 1}.json'
                    replay_path.write_text(json.dumps(replay, indent=2))
                    report['recommendations'].append({'name': final['name'], 'profile': str(replay_path),
                                                     'cost_usd': final['mean_cost_usd'], 'duration': final['mean_duration'],
                                                     'improvements': improvements})
                    winner = {'runner': runner, 'model': final['model']['id'], 'effort': final['effort']}
                    ceiling = {'runner': runner, 'model': ceiling_model, 'effort': ceiling_effort}
                    others = [name for name in ('claude', 'codex', 'grok') if name != runner]
                    pending.append((winner, ceiling, {
                        'run_id': run_id, 'runner': runner, 'workspace': str(workspace),
                        'baseline': {'model': ceiling_model, 'effort': ceiling_effort},
                        'winner': winner, 'improvements': improvements, 'repeats': repeats,
                        'unverified_for': ['cursor'] + others,
                        'mean_duration': final['mean_duration'], 'mean_cost_usd': final['mean_cost_usd'],
                        'mean_total_tokens': final['mean_total_tokens']}))
            if report['recommendations']:
                report['status'] = 'verified_improvement'
                report['cost_savings_verified'] = execution == 'api'
                for winner, ceiling, evidence in pending:
                    write_routing(state_dir, task_class, workspace, winner, ceiling, evidence)
            elif report['provisional_candidates']:
                report['status'] = 'provisional_improvement'
                report['reasons'].append('Fewer than three confirmation runs were requested; improvements remain provisional')
    except (BudgetExceeded, TimeoutError) as exc:
        report['status'] = 'budget_stopped'
        for trial_record in report['trials']:
            if trial_record['status'] == 'passed':
                trial_record['provisional'] = True
        report['reasons'].append(str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        report['reasons'].append(str(exc))
    finally:
        for trial_record in report['trials']:
            if trial_record.get('in_progress'):
                trial_record.update(status='incomplete', provisional=True)
        report['evaluation_cost_usd'] = None if execution == 'current' or budget.uncertain else budget.spent
        report['budget_accounted_usd'] = budget.spent if execution == 'api' else None
        report['invocation_cost_usd'] = budget.spent - previous_spend if execution == 'api' else None
        report['invocation_duration'] = time.monotonic() - started
        report['budget_semantics'] = ('budget-usd is cumulative across resumes; time-limit applies to each invocation' if execution == 'api'
                                      else 'time-limit applies to each invocation; native account billing applies and no dollar ceiling is enforced')
        report['cost_status'] = 'unknown' if execution == 'current' or budget.uncertain else 'metered'
        report['budget_uncertain'] = budget.uncertain
        report['budget_remaining_usd'] = budget.remaining
        report = _redact_value(report, [item.api_key for item in providers.values()])
        store.put('run', run_id, report)
        _write_report(directory, report)
        store.close()
    return report
