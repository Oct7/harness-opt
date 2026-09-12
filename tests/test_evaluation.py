import tempfile
import unittest
from pathlib import Path
from harness_opt.evaluation import *

class EvaluationTests(unittest.TestCase):
    def test_path_escape(self):
        with self.assertRaises(ValueError):
            safe_path('/tmp/work','../outside')
    def test_required_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            case={'required_files':['answer.txt'],'files':{'answer.txt':'result'},'file_contains':{'answer.txt':['result']}}
            self.assertTrue(direct_checks(case,d))
            materialize(case,d)
            self.assertEqual(direct_checks(case,d),[])
    def test_judge_blind_and_swapped(self):
        c={'prompt':'task','criteria':['correct']}
        self.assertIn('whether result B',judge_prompt(c,'base','candidate'))
        self.assertIn('whether result A',judge_prompt(c,'base','candidate',True))
        with self.assertRaises(ValueError):
            semantic_result('{"verdict":"pass"}')
    def test_freeze_and_holdout(self):
        c=[{'kind':k,'prompt':'task','criteria':['correct']} for k in ['normal','normal','boundary','failure']]
        self.assertEqual(validate_cases({'cases':c},4)[-1]['split'],'heldout')

    def test_malformed_generated_shapes(self):
        valid=[{'kind':kind,'prompt':'task','criteria':['correct']} for kind in ['normal','normal','boundary','failure']]
        bad=[[], {'cases':{}}, {'cases':[None]*4}]
        for field,value in [('kind',[]),('prompt',42),('criteria','correct'),('criteria',[{}]),('files',[]),('files',{'a':None}),('required_files','a'),('file_contains',{'a':'x'}),('external_services',{})]:
            cases=[dict(c) for c in valid]
            cases[0][field]=value
            bad.append({'cases':cases})
        for payload in bad:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                validate_cases(payload,4)
        for payload in ['[]','{"verdict":[]}', '{"verdict":"below","reason":[]}']:
            with self.subTest(judge=payload),self.assertRaises(ValueError):
                semantic_result(payload)
