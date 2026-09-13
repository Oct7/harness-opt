import json
from pathlib import Path
import unittest
from importlib.resources import files

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/harness-opt'

class PackageTests(unittest.TestCase):
    def test_marketplace_targets_and_bundled_runtime(self):
        for manifest in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
            self.assertEqual(json.loads((PLUGIN / manifest).read_text())['name'], 'harness-opt')
        claude = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
        codex = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual((ROOT / claude['plugins'][0]['source']).resolve(), PLUGIN)
        self.assertEqual((ROOT / codex['plugins'][0]['source']['path']).resolve(), PLUGIN)
        from harness_opt.runner import public_skill_files
        self.assertEqual([str(p.relative_to(PLUGIN)) for p in public_skill_files(PLUGIN)], ['skills/harness-opt/SKILL.md'])
        self.assertEqual(public_skill_files(PLUGIN / 'examples/file-skill'), [PLUGIN / 'examples/file-skill/SKILL.md'])
        patterns = json.loads(files('harness_opt').joinpath('data/patterns.json').read_text())
        self.assertEqual(len(patterns), 4)
        for pattern in patterns:
            self.assertEqual(len(pattern['commit']), 40)
            self.assertIn(pattern['commit'], pattern['source'])
            self.assertTrue(pattern['license'])
