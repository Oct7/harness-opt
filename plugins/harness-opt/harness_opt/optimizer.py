"""Sequential native-runner experiments, with conservative promotion gates."""
import difflib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .budget import Budget, BudgetExceeded
from .evaluation import direct_checks, json_output, judge_prompt, materialize, semantic_result, validate_cases
from .gateway import Gateway
from .providers import discover_models, load_providers
from .runner import WorkspaceSnapshot, capture_profile, execute, public_skill_files
from .store import Store, fingerprint


def _atomic_text(path,content):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(content)
    os.replace(temporary,path)


def _write_report(directory, report):
    directory.mkdir(parents=True,exist_ok=True)
    _atomic_text(directory/'report.json',json.dumps(report,indent=2,ensure_ascii=False,default=str))
    lines=[f'# harness-opt {report["id"]}', '', f'Status: {report["status"]}',
           f'Mode: {report.get("mode", "unknown")}; confirmation repeats per case: {report.get("confirmation_repeats", "unknown")}',
           f'Evaluation cost (USD): {report.get("evaluation_cost_usd", "unknown")}', '',
           'Recommendations are verified only for the recorded environment and generated cases.', '']
    if report.get('cases_file'):
        lines += ['Frozen cases and held-out split: [cases.json](cases.json)', '']
    for trial in report.get('trials',[]):
        lines.append(f'- {trial["name"]}: {trial["status"]}; cost={trial.get("mean_cost_usd", "unknown")}; duration={trial.get("mean_duration", "unknown")}')
    lines += ['', '## Reasons']+[f'- {x}' for x in report.get('reasons',[])]
    _atomic_text(directory/'report.md','\n'.join(lines)+'\n')


def read_report(run_id, state_dir, format='json'):
    if Path(run_id).name != run_id or run_id in {'.', '..'}:
        raise ValueError('Invalid run ID')
    path=Path(state_dir)/run_id/('report.md' if format=='markdown' else 'report.json')
    return path.read_text() if format=='markdown' else json.loads(path.read_text())


def _native_text(output):
    try:
        data=json.loads(output)
        if isinstance(data,dict) and isinstance(data.get('result'),str):
            return data['result']
        if isinstance(data,dict) and ('cases' in data or 'verdict' in data or 'changes' in data):
            return output
    except (ValueError,TypeError):
        pass
    texts=[]
    for line in output.splitlines():
        try:
            event=json.loads(line)
        except ValueError:
            continue
        if not isinstance(event,dict):
            continue
        item=event.get('item') or {}
        if not isinstance(item,dict):
            continue
        if event.get('type')=='item.completed' and item.get('type')=='agent_message':
            if isinstance(item.get('text'),str):
                texts.append(item['text'])
        if event.get('type')=='result' and isinstance(event.get('result'),str):
            texts.append(event['result'])
    return texts[-1] if texts else output


def _success(result):
    return result.get('status') in ('success','completed','ok')


def _proposal_changes(output):
    data=json_output(_native_text(output))
    if not isinstance(data,dict) or not isinstance(data.get('changes'),dict):
        raise ValueError('Proposal must contain a changes object')
    if any(not isinstance(path,str) or not isinstance(content,str) for path,content in data['changes'].items()):
        raise ValueError('Proposal changes must map paths to complete text content')
    return data['changes']


def _stable_model(model):
    return {k:v for k,v in model.items() if k not in {'checked_date','price_checked_at','verified','checked_at'}}


def _redact_value(value, secrets):
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                value=value.replace(secret,'[REDACTED]')
        return value
    if isinstance(value,dict):
        return {k:_redact_value(v,secrets) for k,v in value.items()}
    if isinstance(value,list):
        return [_redact_value(v,secrets) for v in value]
    return value


def _hashes(workspace):
    import hashlib
    return {str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(workspace).rglob('*') if p.is_file() and not p.is_symlink()}


def _evidence(result, workspace, before, secrets):
    from .runner import _redact
    files={}
    after=_hashes(workspace)
    for name,digest in after.items():
        if before.get(name)==digest or any(part.startswith('.') for part in Path(name).parts):
            continue
        p=Path(workspace)/name
        if any(word in p.name.lower() for word in ('secret','credential','token','apikey','api_key')):
            files[name]={'redacted':True}
            continue
        try:
            files[name]=_redact(p.read_text()) if p.stat().st_size<100000 else {'sha256':digest}
        except UnicodeError:
            files[name]={'sha256':digest}
    return _redact_value({'output':_native_text(result.get('output','')), 'files':files,
                          'deleted_files':sorted(set(before)-set(after))},secrets)


def optimize(target, runner, mode, budget_usd, time_limit, state_dir, env_file,
             baseline_model=None, baseline_provider=None, effort=None, cases=4,
             force=False, resume=None, workspace=None, repeats=3):
    if mode not in {'all','steps','speed','cost','structure'}:
        raise ValueError('Unknown optimization mode')
    if cases < 4:
        raise ValueError('At least four cases are required')
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Repetitions must be an integer of at least 1')
    target=Path(target).resolve()
    if not target.exists():
        raise ValueError('Target does not exist')
    workspace=Path(workspace or (target.parent if target.is_file() else target)).resolve()
    if not target.is_relative_to(workspace):
        raise ValueError('Target must be inside workspace')
    state_dir=Path(state_dir).resolve()
    if state_dir.is_relative_to(workspace):
        raise ValueError('State directory must be outside the experiment workspace')
    run_id=resume or uuid.uuid4().hex[:12]
    if '/' in run_id or '\\' in run_id or run_id in {'.','..'}:
        raise ValueError('Invalid run ID')
    directory=state_dir/run_id
    state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Run directories are harness-owned and contain private workspace snapshots.
    directory.chmod(0o700)
    store=Store(state_dir/'history.sqlite3')
    budget=Budget(budget_usd,time_limit,on_change=lambda state:store.put('budget',run_id,state))
    started=time.monotonic()
    previous_spend=0.0
    report={'id':run_id,'status':'no_verified_improvement','trials':[],'reasons':[],
            'recommendations':[],'provisional_candidates':[], 'mode':mode,
            'confirmation_repeats':repeats,'scope':'recorded environment and generated cases only'}
    profile=capture_profile(runner,workspace,model=baseline_model,effort=effort)
    if profile.get('requires_external_fixture') and not profile.get('external_isolation_verified'):
        raise ValueError('Native hooks/MCP require an independently isolated external fixture before optimization')
    effort=profile.get('effort')
    providers=load_providers(env_file)
    if baseline_provider is None and len(providers)==1:
        baseline_provider=next(iter(providers))
    if baseline_provider not in providers:
        raise ValueError('Specify a configured baseline provider')
    models=[]
    for provider in providers.values():
        models.extend(discover_models(provider))
    model_id=baseline_model or profile.get('model')
    baseline=next((m for m in models if m['id']==model_id and m['provider']==baseline_provider),None)
    if baseline is None:
        raise ValueError('Baseline model must match the captured native configuration and a discovered model')
    if not model_id:
        raise ValueError('Cannot establish the current model; provide --baseline-model')
    snapshot=WorkspaceSnapshot(workspace,directory/('snapshot-'+uuid.uuid4().hex[:8]))
    skill_files=public_skill_files(target)
    if not skill_files:
        raise ValueError('Target has no public SKILL.md entrypoints')
    relative=target.relative_to(workspace)
    original={str(p.relative_to(workspace)):p.read_text() for p in skill_files}
    identity=fingerprint({'workspace':snapshot.fingerprint,'profile':profile,'skills':original,'cases':cases,'baseline':_stable_model(baseline)})
    previous=store.get('run',run_id)
    if previous and previous.get('identity')!=identity:
        raise ValueError('Resume configuration differs from original run')
    journal=store.get('budget',run_id)
    if journal:
        pending=sum(journal.get('reservations',{}).values())
        previous_spend=journal.get('spent',0)+pending
        budget.spent=previous_spend
        budget.uncertain=journal.get('uncertain',False) or bool(pending)
    elif previous:
        previous_spend=previous.get('budget_accounted_usd',previous.get('evaluation_cost_usd')) or 0
        budget.spent=previous_spend
        budget.uncertain=previous.get('budget_uncertain',False)
    report.update(identity=identity,profile=profile,baseline=baseline,workspace_fingerprint=snapshot.fingerprint)
    store.put('run',run_id,report)

    def call(prompt,model,work,selected_effort=effort,target_path=None,entrypoint=None):
        if not budget.time_left or not budget.remaining:
            raise BudgetExceeded('Budget or time limit reached')
        with Gateway(providers[model['provider']],model,budget,effort=selected_effort) as gateway:
            active=dict(profile,model=model['id'],effort=selected_effort,gateway_api_key=gateway.api_key,entrypoint=entrypoint,evaluation_only=target_path is None)
            result=execute(active,work,prompt,gateway.base_url,budget.time_left,target=target_path)
        result=_redact_value(result,[p.api_key for p in providers.values()])
        result.update(cost_usd=gateway.cost,calls=gateway.records,compatibility_errors=gateway.compatibility_errors)
        if gateway.compatibility_errors:
            result['status']='compatibility_failure'
        if not gateway.records:
            result['status']='unverified'
            result['reason']='No metered model calls; native gateway routing was not verified'
        errors={r.get('error') for r in gateway.records if r.get('error')}
        if errors:
            result['status']=next((category+'_failure' for category in ('compatibility','authentication','transport','budget') if category in errors),'unverified')
        report.setdefault('calls',[]).append({'model':model['id'],'result':result})
        report['evaluation_cost_usd']=None if budget.uncertain else budget.spent
        report['budget_accounted_usd']=budget.spent
        store.put('run',run_id,report)
        _write_report(directory,report)
        if 'budget' in errors:
            raise BudgetExceeded('Gateway could not reserve the next call within the configured budget')
        return result

    def judge(case,base,candidate,swapped):
        work=directory/('judge-work-'+uuid.uuid4().hex[:8])
        work.mkdir()
        result=call(judge_prompt(case,base,candidate,swapped),baseline,work)
        if not _success(result):
            return {'verdict':'indeterminate','reason':result.get('reason',result['status'])}
        return semantic_result(_native_text(result['output']))

    def trial(name,model,changes,selected_effort,case_set,repeats=1):
        key=fingerprint({'identity':identity,'model':_stable_model(model),'effort':selected_effort,'changes':changes,'cases':case_set,'repeats':repeats})
        cached=None if force else store.failure(key,versioned=bool(model.get('model_version')) and not bool(model.get('alias_target')))
        if cached:
            reused=dict(cached,name=name,reused=True)
            report['trials'].append(reused)
            return reused
        record={'name':name,'model':_stable_model(model),'effort':selected_effort,'changes':changes,'status':'passed','runs':[],'reused':False,'in_progress':True}
        report['trials'].append(record)
        for case in case_set:
            if case.get('unverified_reason') or case['id'] not in baselines:
                record['status']='unverified'
                continue
            for repeat in range(repeats):
                work=snapshot.restore(directory/('trial-work-'+uuid.uuid4().hex[:8]))
                materialize(case,work)
                for path,content in changes.items():
                    from .evaluation import safe_path
                    changed=safe_path(work,path)
                    changed.parent.mkdir(parents=True,exist_ok=True)
                    changed.write_text(content)
                before=_hashes(work)
                result=call(case['prompt'],model,work,selected_effort,work/relative,case.get('entrypoint'))
                errors=direct_checks(case,work)
                evidence=_evidence(result,work,before,[p.api_key for p in providers.values()])
                judges=[]
                if _success(result) and not errors:
                    judges=[judge(case,baselines[case['id']]['evidence'],evidence,False),judge(case,baselines[case['id']]['evidence'],evidence,True)]
                record['runs'].append({'case':case['id'],'repeat':repeat,'result':result,'checks':errors,'judges':judges})
                if errors or any(j['verdict']=='below' for j in judges):
                    record['status']='quality_failure'
                elif not _success(result) or not judges or any(j['verdict']=='indeterminate' for j in judges):
                    record['status']='unverified'
                if record['status']!='passed':
                    break
            if record['status']!='passed':
                break
        runs=record['runs']
        record['mean_duration']=sum(r['result'].get('duration',0) for r in runs)/len(runs) if runs else None
        costs=[r['result']['cost_usd'] for r in runs]
        record['mean_cost_usd']=sum(costs)/len(costs) if costs and all(c is not None for c in costs) else None
        if record['status']=='quality_failure':
            store.put('failure',key,record)
        record['in_progress']=False
        report['evaluation_cost_usd']=None if budget.uncertain else budget.spent
        report['budget_accounted_usd']=budget.spent
        _write_report(directory,report)
        return record

    baselines={}
    try:
        case_key=fingerprint({'identity':identity,'generator':1})
        case_set=None if force else store.get('cases',case_key)
        report['cases_reused']=case_set is not None
        if case_set is None:
            case_set=[]
            for entry,source in original.items():
                work=snapshot.restore(directory/('generation-work-'+uuid.uuid4().hex[:8]))
                prompt=('Generate independent evaluation cases for this public skill entrypoint. '
                        f'Return ONLY JSON {{"cases":[...]}} with exactly {cases} cases (at least 2 normal, 1 boundary, 1 failure). '
                        'Each case has kind, prompt, criteria (requirements based ONLY on original instructions), files (relative path:text fixtures), '
                        'required_files (paths), file_contains (path:list of literal strings only where semantically required), external_services (list). '
                        'Use fully local reproducible tasks. Do not execute the skill.\n'+json.dumps({entry:source}))
                generated=call(prompt,baseline,work)
                if not _success(generated):
                    raise ValueError('Case generation did not complete with verified metering')
                entry_cases=validate_cases(json_output(_native_text(generated['output'])),cases)
                for case in entry_cases:
                    case['entrypoint']=entry
                    case['id']=f'{entry}:{case["id"]}'
                case_set.extend(entry_cases)
            store.put('cases',case_key,case_set)
        for case in case_set:
            for fixture in case.get('files',{}):
                from .evaluation import safe_path
                fixture_path=safe_path(workspace,fixture)
                if fixture_path.exists() or any(part.startswith('.') for part in Path(fixture).parts):
                    case['unverified_reason']='Generated fixture would overwrite an existing file or native configuration'
        report['cases']=case_set
        report['cases_file']=str(directory/'cases.json')
        _atomic_text(directory/'cases.json',json.dumps({'cases':case_set},indent=2,ensure_ascii=False))
        _write_report(directory,report)
        for case in case_set:
            if case.get('unverified_reason'):
                report['reasons'].append(case['unverified_reason'])
                continue
            work=snapshot.restore(directory/('baseline-work-'+uuid.uuid4().hex[:8]))
            materialize(case,work)
            before=_hashes(work)
            result=call(case['prompt'],baseline,work,target_path=work/relative,entrypoint=case.get('entrypoint'))
            errors=direct_checks(case,work)
            if _success(result) and not errors:
                baselines[case['id']]={'result':result,'evidence':_evidence(result,work,before,[p.api_key for p in providers.values()])}
            else:
                report.setdefault('baseline_failures',[]).append({'case':case['id'],'result':result,'checks':errors})
                report['reasons'].append(f'Baseline {case["id"]} failed: {errors or result["status"]}')
        report['baseline_runs']={k:{'result':v['result']} for k,v in baselines.items()}
        explore=[c for c in case_set if c['split']=='exploration']
        passing=[]
        if mode in {'all','steps','structure'}:
            for kind in (['steps','structure'] if mode=='all' else [mode]):
                work=snapshot.restore(directory/('proposal-work-'+uuid.uuid4().hex[:8]))
                patterns_path=Path(__file__).resolve().parent/'data'/'patterns.json'
                patterns=json.loads(patterns_path.read_text()) if kind=='structure' and patterns_path.exists() else []
                proposal=call('Propose ONE '+kind+' optimization. Preserve every user requirement, output, security and permission condition. '
                    'Consolidate duplicate instructions, extract optional reads into references, or repeated work into scripts. '
                    'Return ONLY JSON {"changes":{"relative file path within the target":"complete replacement text"},"reason":"..."}. '
                    'Do not use heldout cases.\n'+json.dumps({'skills':original,'patterns':patterns}),baseline,work)
                if not _success(proposal):
                    continue
                changes=_proposal_changes(proposal['output'])
                valid=bool(changes)
                from .evaluation import safe_path
                target_root=target.parent if target.is_file() else target
                for path,content in changes.items():
                    try:
                        changed=safe_path(workspace,path)
                        if not changed.is_relative_to(target_root) or not isinstance(content,str) or not content.strip():
                            valid=False
                        if changed.exists():
                            changed.read_text()  # Do not replace binary resources with generated text.
                    except (ValueError,UnicodeError,OSError):
                        valid=False
                if not valid:
                    report['reasons'].append(f'{kind}: unsafe, binary or empty proposal')
                    continue
                changes={path:content for path,content in changes.items()
                         if not (workspace/path).is_file() or (workspace/path).read_text()!=content}
                if not changes:
                    report['reasons'].append(f'{kind}: proposal makes no changes')
                    continue
                record=trial(kind,baseline,changes,effort,explore)
                if record['status']=='passed':
                    passing.append(record)
        if mode in {'all','speed','cost'}:
            for model in sorted(models,key=lambda m:m.get('input_per_million') if m.get('input_per_million') is not None else float('inf')):
                if any(model.get(k) is None for k in ('input_per_million','output_per_million','context_window')):
                    continue
                for candidate_effort in model.get('efforts') or []:
                    if model==baseline and candidate_effort==effort:
                        continue
                    record=trial(f'{model["provider"]}/{model["id"]}:{candidate_effort}',model,{},candidate_effort,explore)
                    if record['status']=='passed':
                        passing.append(record)
        # Confirmation includes held-out cases; fewer than three runs stay provisional.
        finalists=list(passing)
        change_trials=[p for p in passing if p['changes']]
        model_trials=[p for p in passing if not p['changes']]
        if mode=='all' and change_trials:
            changes={}
            conflicts=False
            for p in change_trials:
                conflicts=conflicts or bool(set(changes)&set(p['changes']))
                changes.update(p['changes'])
            if conflicts:
                work=snapshot.restore(directory/('combine-work-'+uuid.uuid4().hex[:8]))
                proposal=call('Combine ALL individually passing optimizations below into one coherent change. '
                    'Preserve all original requirements, permissions, security and outputs. '
                    'Return ONLY JSON {"changes":{"relative path":"complete file content"}}. '
                    'Use only paths present in the passing changes.\n'+json.dumps({'original':original,'passing':[p['changes'] for p in change_trials]}),baseline,work)
                combined=_proposal_changes(proposal['output']) if _success(proposal) else {}
                if not combined or not set(combined)<=set(changes) or any(not isinstance(v,str) or not v.strip() for v in combined.values()):
                    changes={}
                    report['reasons'].append('Combined change proposal was invalid')
                else:
                    changes=combined
            if changes:
                combined_trial=trial('combined-changes',baseline,changes,effort,explore)
                if combined_trial['status']=='passed':
                    finalists.append(combined_trial)
                    for p in model_trials:
                        finalists.append(dict(p,name='combined:'+p['name'],changes=changes))
        if len(baselines)==len(case_set):
            base_costs=[b['result']['cost_usd'] for b in baselines.values()]
            base_cost=sum(base_costs)/len(base_costs) if all(c is not None for c in base_costs) else None
            base_time=sum(b['result']['duration'] for b in baselines.values())/len(baselines)
            for candidate in finalists:
                final=trial('confirm:'+candidate['name'],candidate['model'],candidate['changes'],candidate['effort'],case_set,repeats)
                if final['status']=='passed' and base_cost is not None and final['mean_cost_usd'] is not None and final['mean_cost_usd']<base_cost and final['mean_duration']<base_time:
                    if repeats < 3:
                        final['provisional']=True
                        report['provisional_candidates'].append({'name':final['name'],'cost_usd':final['mean_cost_usd'],
                                                               'duration':final['mean_duration'],'repeats':repeats})
                        continue
                    index=len(report['recommendations'])+1
                    copy=snapshot.restore(directory/f'approved-{index}-{uuid.uuid4().hex[:8]}')
                    diff=[]
                    for p,content in final['changes'].items():
                        (copy/p).parent.mkdir(parents=True,exist_ok=True)
                        (copy/p).write_text(content)
                        diff.extend(difflib.unified_diff(((workspace/p).read_text() if (workspace/p).exists() else '').splitlines(True),content.splitlines(True),fromfile=p,tofile=p))
                    (directory/f'approved-{index}.diff').write_text(''.join(diff))
                    replay={'runner_profile':dict(profile,model=final['model']['id'],effort=final['effort']), 'provider':final['model']['provider'],'model':final['model'],'workspace':str(copy),'target':str(copy/relative),'verified_scope':report['scope'],'confirmation_repeats':repeats,'approved_hash':WorkspaceSnapshot(copy,directory/('integrity-'+uuid.uuid4().hex[:8])).fingerprint}
                    replay_path=directory/f'profile-{index}.json'
                    replay_path.write_text(json.dumps(replay,indent=2))
                    report['recommendations'].append({'name':final['name'],'profile':str(replay_path),'cost_usd':final['mean_cost_usd'],'duration':final['mean_duration']})
            if report['recommendations']:
                report['status']='verified_improvement'
            elif report['provisional_candidates']:
                report['status']='provisional_improvement'
                report['reasons'].append('Fewer than three confirmation runs were requested; improvements remain provisional')
    except (BudgetExceeded,TimeoutError) as exc:
        report['status']='budget_stopped'
        for trial_record in report['trials']:
            if trial_record['status']=='passed':
                trial_record['provisional']=True
        report['reasons'].append(str(exc))
    except (ValueError,RuntimeError,OSError) as exc:
        report['reasons'].append(str(exc))
    finally:
        for trial_record in report['trials']:
            if trial_record.get('in_progress'):
                trial_record.update(status='incomplete',provisional=True)
        report['evaluation_cost_usd']=None if budget.uncertain else budget.spent
        report['budget_accounted_usd']=budget.spent
        report['invocation_cost_usd']=budget.spent-previous_spend
        report['invocation_duration']=time.monotonic()-started
        report['budget_semantics']='budget-usd is cumulative across resumes; time-limit applies to each invocation'
        report['budget_uncertain']=budget.uncertain
        report['budget_remaining_usd']=budget.remaining
        report=_redact_value(report,[p.api_key for p in providers.values()])
        store.put('run',run_id,report)
        _write_report(directory,report)
        store.close()
    return report


def run_profile(profile_path, task, budget_usd, time_limit, env_file=None, workspace=None):
    import tempfile
    data=json.loads(Path(profile_path).read_text())
    providers=load_providers(env_file)
    budget=Budget(budget_usd,time_limit)
    if data['provider'] not in providers:
        raise ValueError('Profile provider is not configured')
    available=discover_models(providers[data['provider']])
    selected=next((m for m in available if m['id']==data['model']['id']),None)
    if selected is None:
        raise ValueError('Profile model is not available from the configured provider')
    if data['model'].get('model_version') and data['model'].get('model_version')!=selected.get('model_version'):
        raise ValueError('Model version changed; re-optimize before running')
    approved=Path(data['workspace'])
    source=Path(workspace or Path.cwd()).resolve()
    if not source.is_dir():
        raise ValueError('Task workspace must be an existing source directory')
    with tempfile.TemporaryDirectory(prefix='harness-opt-run-') as tmp:
        snapshot=WorkspaceSnapshot(approved,Path(tmp)/'approved')
        if snapshot.fingerprint != data.get('approved_hash'):
            raise ValueError('Approved workspace changed; re-optimize before running')
        destination=Path(tempfile.mkdtemp(prefix='harness-opt-result-'))/'workspace'
        task_snapshot=WorkspaceSnapshot(source,Path(tmp)/'source')
        work=task_snapshot.restore(destination)
        approved_target=Path(data['target'])
        if not approved_target.resolve().is_relative_to(approved.resolve()):
            raise ValueError('Profile target is outside the approved workspace')
        target=work/'.harness-approved-target'/approved_target.name
        target.parent.mkdir(parents=True,exist_ok=True)
        if approved_target.is_file():
            shutil.copytree(approved_target.parent,target.parent/'skill')
            target=target.parent/'skill'/approved_target.name
        else:
            shutil.copytree(approved_target,target)
        with Gateway(providers[data['provider']],selected,budget,effort=data['runner_profile'].get('effort')) as gateway:
            active=dict(data['runner_profile'],gateway_api_key=gateway.api_key)
            result=execute(active,work,task,gateway.base_url,budget.time_left,target=target)
        result.update(cost_usd=gateway.cost,compatibility_errors=gateway.compatibility_errors,workspace=str(work))
        if gateway.compatibility_errors or not gateway.records:
            result['status']='unverified'
        return _redact_value(result,[p.api_key for p in providers.values()])
