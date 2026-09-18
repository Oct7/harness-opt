import unittest
from harness_opt.runner import (
    catalog_fingerprint, efforts_to_ceiling, native_models, parse_codex_catalog,
    parse_cursor_cli_config, parse_listed_models,
)


class NativeModelsTests(unittest.TestCase):
    def test_parse_listed_models_keeps_ids_and_efforts(self):
        rows = parse_listed_models([
            {'id': 'grok-4.6', 'efforts': ['low', 'high', 'xhigh']},
            {'id': 'composer-2.5-fast', 'efforts': ['low']},
        ])
        self.assertEqual([r['id'] for r in rows], ['grok-4.6', 'composer-2.5-fast'])
        self.assertEqual(rows[0]['efforts'], ['low', 'high', 'xhigh'])

    def test_parse_rejects_empty_and_non_ids(self):
        self.assertEqual(parse_listed_models(['', None, {'name': 'x'}]), [])

    def test_native_models_uses_profile_catalog_for_every_host(self):
        catalog = [{'id': 'a', 'provider': 'native', 'efforts': ['low', 'high']},
                   {'id': 'b', 'provider': 'native', 'efforts': ['high']}]
        for host in ('claude', 'codex', 'grok', 'cursor'):
            self.assertEqual(native_models(host, {'catalog': catalog}), catalog)

    def test_cursor_measurement_is_error(self):
        with self.assertRaisesRegex(ValueError, 'cursor'):
            native_models('cursor', {'measurement': True, 'catalog': [{'id': 'x', 'efforts': ['low']}]})

    def test_empty_catalog_is_empty_list(self):
        self.assertEqual(native_models('claude', {'catalog': []}), [])

    def test_fingerprint_changes_when_ids_change(self):
        a = [{'id': 'a', 'efforts': ['low']}]
        b = [{'id': 'a', 'efforts': ['low']}, {'id': 'b', 'efforts': ['high']}]
        self.assertNotEqual(catalog_fingerprint(a), catalog_fingerprint(b))

    def test_cursor_cli_config_keeps_disk_ids(self):
        models, ceiling = parse_cursor_cli_config({
            'model': {'modelId': 'grok-4.6'},
            'selectedModel': {'modelId': 'grok-4.6', 'parameters': [{'id': 'effort', 'value': 'xhigh'}]},
            'modelSelectionHistory': ['grok-4.6'],
            'modelParameters': {'grok-4.6': [{'id': 'effort', 'value': 'xhigh'}]},
        })
        self.assertEqual(ceiling, {'model': 'grok-4.6', 'effort': 'xhigh'})
        self.assertEqual([row['id'] for row in models], ['grok-4.6'])
        self.assertEqual(models[0]['efforts'], ['low', 'medium', 'high', 'xhigh'])

    def test_efforts_to_ceiling_stops_at_disk_value(self):
        self.assertEqual(efforts_to_ceiling('high'), ['low', 'medium', 'high'])
        self.assertEqual(efforts_to_ceiling(None), [])

    def test_codex_catalog_uses_slug_and_listed_efforts(self):
        rows = parse_codex_catalog({'models': [
            {'slug': 'gpt-5.6-sol', 'supported_reasoning_levels': [
                {'effort': 'low'}, {'effort': 'high'}, {'effort': 'ultra'}]},
            {'display_name': 'skip'},
        ]})
        self.assertEqual(rows, [{'id': 'gpt-5.6-sol', 'provider': 'native',
                                 'efforts': ['low', 'high', 'ultra']}])
