import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from harness_opt.providers import Provider, discover_models, load_providers, usage_cost

class ProviderTests(unittest.TestCase):
    def test_discovery(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'data': [{'id': 'test', 'pricing': {'prompt': '0.000001', 'completion': '0.000002'}, 'context_length': 1000}]}).encode())
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            models = discover_models(Provider('test', f'http://127.0.0.1:{server.server_port}', 'secret'))
            self.assertEqual(models[0]['input_per_million'], 1)
            self.assertFalse(models[0]['verified'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_load_and_no_secret_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('HARNESS_TEST_BASE_URL=https://example.org/v1\nHARNESS_TEST_API_KEY=secret\n')
            provider = load_providers(path)['test']
            self.assertNotIn('secret', repr(provider))

    def test_cache_reasoning_not_double_counted(self):
        model = {'input_per_million': 1, 'output_per_million': 2, 'cache_read_per_million': .1}
        usage = {'input_tokens': 100, 'output_tokens': 50, 'input_tokens_details': {'cached_tokens': 20}, 'output_tokens_details': {'reasoning_tokens': 30}}
        self.assertAlmostEqual(usage_cost(usage, model)[0], .000182)
        self.assertIsNone(usage_cost({'input_tokens': 1, 'output_tokens': 2, 'cache_creation_input_tokens': 4}, model)[0])

    def test_invalid_usage_and_tiers(self):
        from harness_opt.providers import normalize_model
        model = normalize_model({'id': 'tiered', 'pricing': {'prompt': '.000001', 'completion': '.000002', 'input_cache_read': '.0000001', 'overrides': [{'min_prompt_tokens': 100, 'prompt': '.000002', 'completion': '.000003'}]}, 'reasoning': {'supported_efforts': ['low']}, 'top_provider': {'max_completion_tokens': 50}}, Provider('test', 'http://localhost/v1', ''))
        self.assertEqual(model['efforts'], ['low'])
        self.assertEqual(model['max_output_tokens'], 50)
        self.assertAlmostEqual(usage_cost({'input_tokens': 100, 'output_tokens': 10}, model)[0], .00023)
        for bad in (-1, 'invalid', {}, float('nan'), True):
            self.assertIsNone(usage_cost({'input_tokens': bad, 'output_tokens': 10}, model)[0])
        self.assertIsNone(usage_cost({'input_tokens': 10, 'output_tokens': 10}, {**model, 'output_per_million': -1})[0])

    def test_anthropic_cache_counts_towards_price_tier(self):
        model={'input_per_million':1,'output_per_million':1,'cache_read_per_million':.1,'cache_write_per_million':1.25,'pricing':{'overrides':[{'min_prompt_tokens':100,'prompt':'.000002','completion':'.000002','input_cache_read':'.0000002'}]}}
        self.assertAlmostEqual(usage_cost({'input_tokens':10,'output_tokens':10,'cache_read_input_tokens':100},model)[0],.00006)
        self.assertIsNone(usage_cost({'input_tokens':10,'output_tokens':10,'cache_creation_input_tokens':100,'cache_creation':{'ephemeral_1h_input_tokens':100}},model)[0])
