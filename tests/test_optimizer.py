import json
import unittest
from harness_opt.optimizer import _native_text

class OptimizerTests(unittest.TestCase):
    def test_native_final_output(self):
        self.assertEqual(_native_text(json.dumps({'type':'result','result':'{"cases":[]}'})),'{"cases":[]}')
        self.assertEqual(_native_text('{"type":"thread.started"}\n'+json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'final'}})),'final')

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from harness_opt.optimizer import optimize, run_profile

class WorkflowTests(unittest.TestCase):
    def experiment(self, cheap_cost=0.01, missing=False, mode="cost", combined_failure=False, resume_budget=False, repeats=3, nested_example=False, legacy_profile=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); work=root/'source';work.mkdir();(work/'SKILL.md').write_text('Write answer.txt with correct result')
            if nested_example:
                (work/'examples/nested').mkdir(parents=True)
                (work/'examples/nested/SKILL.md').write_text('An example, not a public entrypoint')
            provider=SimpleNamespace(api_key='secret-fixture')
            models=[{'provider':'fake','id':name,'input_per_million':price,'output_per_million':price,'context_window':100,'efforts':['low']} for name,price in [('base',2),('cheap',1)]]
            active={}
            class FakeGateway:
                def __init__(self,provider,model,budget,effort=None):
                    self.budget=budget;self.model=model;self.api_key='temporary';self.base_url='fake';self.compatibility_errors=[];self.records=[];self.cost=0
                def __enter__(self):
                    self.reservation=self.budget.reserve(0.02 if self.model['id']=='base' else cheap_cost)
                    active['gateway']=self
                    return self
                def __exit__(self,*args):
                    self.budget.settle(self.reservation,self.cost)
            def fake_execute(profile,workspace,prompt,gateway_url,timeout,target=None):
                g=active['gateway'];g.cost=0.02 if profile['model']=='base' else cheap_cost;g.records=[{'cost':g.cost}]
                self.assertEqual(profile['effort'],'low')
                if 'Generate independent' in prompt:
                    output=json.dumps({'cases':[{'kind':kind,'prompt':'write result','criteria':['correct file'],'required_files':['answer.txt'],'file_contains':{'answer.txt':['correct']}} for kind in ['normal','normal','boundary','failure']]})
                elif 'Propose ONE' in prompt:
                    marker='steps' if 'ONE steps' in prompt else 'structure'
                    output=json.dumps({'changes':{'SKILL.md':'Write answer.txt with correct result '+marker}})
                elif 'Combine ALL' in prompt:
                    output=json.dumps({'changes':{'SKILL.md':'Write answer.txt with correct result steps structure'}})
                elif 'Evaluate two anonymous' in prompt:
                    output='{"verdict":"equivalent_or_better","reason":"same required result"}'
                else:
                    combined=combined_failure and profile['model']=='cheap' and (Path(workspace)/'SKILL.md').exists() and 'steps structure' in (Path(workspace)/'SKILL.md').read_text()
                    if (not missing or profile['model']=='base') and not combined:
                        (Path(workspace)/'answer.txt').write_text('correct')
                    output='done'
                return {'status':'completed','output':output,'duration':2 if profile['model']=='base' else 1,'artifacts':{}}
            profile={'runner':'codex','model':'base','effort':'low','version':'test','workspace':str(work)}
            with patch('harness_opt.optimizer.capture_profile',return_value=profile),patch('harness_opt.optimizer.load_providers',return_value={'fake':provider}),patch('harness_opt.optimizer.discover_models',return_value=models),patch('harness_opt.optimizer.Gateway',FakeGateway),patch('harness_opt.optimizer.execute',side_effect=fake_execute):
                result=optimize(work,'codex',mode,0.065 if resume_budget else 10,60,root/'state',None,repeats=repeats,execution='api')
                case_file=Path(result['cases_file'])
                frozen=json.loads(case_file.read_text())['cases']
                self.assertEqual(frozen,result['cases'])
                self.assertEqual([c['split'] for c in frozen],['exploration','exploration','exploration','heldout'])
                self.assertEqual(result['confirmation_repeats'],repeats)
                if resume_budget:
                    self.assertEqual(result['status'],'budget_stopped')
                    prior=result['evaluation_cost_usd']
                    result=optimize(work,'codex',mode,10,60,root/'state',None,resume=result['id'],execution='api')
                    self.assertGreater(result['evaluation_cost_usd'],prior)
                    self.assertAlmostEqual(result['evaluation_cost_usd']-result['invocation_cost_usd'],prior)
                if missing:
                    self.assertEqual(result['trials'][0]['status'],'quality_failure')
                    repeated=optimize(work,'codex','cost',10,60,root/'state',None,execution='api')
                    self.assertTrue(repeated['trials'][0]['reused'])
                    return
                if cheap_cost>=0.02:
                    self.assertEqual(result['status'],'no_verified_improvement')
                    self.assertEqual(result['recommendations'],[])
                    return
                if repeats < 3:
                    self.assertEqual(result['status'],'provisional_improvement',result['reasons'])
                    self.assertEqual(result['recommendations'],[])
                    self.assertTrue(result['provisional_candidates'])
                    self.assertEqual(len(result['trials'][-1]['runs']),4)
                    return
                self.assertEqual(result['status'],'verified_improvement',result['reasons'])
                self.assertEqual((root/'state'/result['id']).stat().st_mode & 0o777,0o700)
                from harness_opt.optimizer import read_report
                self.assertEqual(read_report(result['id'],root/'state')['id'],result['id'])
                if combined_failure:
                    self.assertTrue(any(t['name'].startswith('confirm:combined:') and t['status']=='quality_failure' for t in result['trials']))
                    self.assertFalse(any('combined' in r['name'] for r in result['recommendations']))
                    return
                self.assertEqual(len(result['trials'][-1]['runs']),20 if repeats==5 else 12)
                self.assertFalse((work/'answer.txt').exists())
                task_source=root/'new-task'
                task_source.mkdir()
                (task_source/'input.txt').write_text('new task input')
                replay_path=Path(result['recommendations'][0]['profile'])
                if legacy_profile:
                    saved=json.loads(replay_path.read_text())
                    self.assertEqual(saved.pop('execution'),'api')
                    replay_path.write_text(json.dumps(saved))
                replay=run_profile(replay_path,'write result',1,20,workspace=task_source)
                self.assertEqual(replay['status'],'completed')
                self.assertEqual(replay['execution'],'api')
                self.assertTrue((Path(replay['workspace'])/'answer.txt').exists())
                self.assertEqual((Path(replay['workspace'])/'input.txt').read_text(),'new task input')
                self.assertFalse((task_source/'answer.txt').exists())

    def test_full_local_experiment_and_replay(self):
        self.experiment()

    def test_legacy_replay_profile_uses_metered_api(self):
        self.experiment(legacy_profile=True)

    def test_nested_example_is_not_a_public_entrypoint(self):
        self.experiment(nested_example=True)

    def test_selected_repetitions_are_executed(self):
        self.experiment(repeats=5)

    def test_single_repeat_is_provisional(self):
        self.experiment(repeats=1)

    def test_cheaper_unit_price_expensive_output_excluded(self):
        self.experiment(cheap_cost=0.04)

    def test_missing_file_failure_reused(self):
        self.experiment(missing=True)

    def test_passing_individuals_failing_combination_excluded(self):
        self.experiment(mode='all',combined_failure=True)

    def test_budget_stop_resume_cumulative_spend(self):
        self.experiment(resume_budget=True)

class IntegrityTests(unittest.TestCase):
    def test_malformed_proposal_and_native_events(self):
        from harness_opt.optimizer import _proposal_changes
        for value in ['[]','{"changes":[]}','{"changes":{"path":null}}','```']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                _proposal_changes(value)
        self.assertEqual(_native_text('null\n42\n{"item":[]}'),'null\n42\n{"item":[]}')

    def test_model_check_dates_do_not_invalidate_failure_cache(self):
        from harness_opt.optimizer import _stable_model
        self.assertEqual(_stable_model({'id':'a','verified':True,'checked_date':'today'}),_stable_model({'id':'a','verified':False,'checked_date':'tomorrow'}))

    def test_evidence_changed_only_and_secret_redaction(self):
        from harness_opt.optimizer import _evidence, _hashes
        with tempfile.TemporaryDirectory() as d:
            w=Path(d)
            (w/'existing.txt').write_text('unchanged input')
            before=_hashes(w)
            (w/'result.txt').write_text('value secret"with-quotes')
            (w/'credentials.json').write_text('{"key":"other-secret"}')
            result={'output':json.dumps({'result':'answer','modelUsage':{'private-model':{'cost':42}}})}
            evidence=_evidence(result,w,before,['secret"with-quotes'])
            self.assertEqual(evidence['output'],'answer')
            self.assertNotIn('existing.txt',evidence['files'])
            self.assertEqual(evidence['files']['result.txt'],'value [REDACTED]')
            self.assertEqual(evidence['files']['credentials.json'],{'redacted':True})
