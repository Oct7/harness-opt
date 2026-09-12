import asyncio
import sys
import types
import unittest
from unittest.mock import patch
from harness_opt.budget import Budget
from harness_opt.gateway import Gateway, CompatibilityError
from harness_opt.providers import Provider

class GatewayTests(unittest.TestCase):
    def gateway(self):
        return Gateway(Provider('test', 'https://example.org/v1', 'secret'), {'id': 'test', 'litellm_model': 'test/test', 'input_per_million': 1, 'output_per_million': 2, 'context_window': 1000, 'efforts': ['low']}, Budget(1, 10))

    def test_measured_usage(self):
        captured = {}
        async def call(**kwargs):
            captured.update(kwargs)
            return {'usage': {'input_tokens': 10, 'output_tokens': 20}}
        module = types.SimpleNamespace(aresponses=call)
        gateway = self.gateway()
        with patch.dict(sys.modules, {'litellm': module}):
            asyncio.run(gateway.execute('/v1/responses', {'model': 'test', 'input': 'hi'}))
        self.assertAlmostEqual(gateway.cost, .00005)
        self.assertEqual(captured['num_retries'], 0)
        self.assertFalse(captured['drop_params'])
        self.assertNotIn('secret', str(gateway.records))

    def test_fixed_unknown_and_effort_fail(self):
        gateway = self.gateway()
        for body in ({'model': 'fixed-subagent'}, {'model': 'test', 'reasoning': {'effort': 'high'}}):
            with self.assertRaises(CompatibilityError):
                asyncio.run(gateway.execute('/responses', body))
        self.assertEqual(len(gateway.compatibility_errors), 2)
        self.assertEqual(gateway.budget.spent, 0)

    def test_streaming(self):
        async def chunks():
            yield {'type': 'response.output_text.delta', 'delta': 'Hi'}
            yield {'type': 'response.completed', 'response': {'usage': {'input_tokens': 10, 'output_tokens': 2}}}
        async def call(**kwargs): return chunks()
        gateway = self.gateway()
        seen = []
        with patch.dict(sys.modules, {'litellm': types.SimpleNamespace(aresponses=call)}):
            asyncio.run(gateway.execute('/responses', {'model': 'test', 'input': 'hi', 'stream': True}, seen.append))
        self.assertEqual(len(seen), 2)
        self.assertIsNotNone(gateway.records[0]['ttft'])
        self.assertAlmostEqual(gateway.cost, .000014)

class RealLiteLLMTests(unittest.TestCase):
    """Exercise installed LiteLLM against a loopback HTTP provider, without API keys."""
    def test_http_streams_and_tools(self):
        import importlib.util
        if importlib.util.find_spec('litellm') is None:
            self.skipTest('Install package dependencies to exercise real LiteLLM')
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
                self.end_headers()
                if self.path.endswith('/chat/completions'):
                    common = {'id': 'chatcmpl-test', 'created': 1, 'model': 'gpt-4o-mini'}
                    tool = {'id': 'call_test', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{"path":"out.txt"}'}}
                    if body.get('stream'):
                        chunks = [{**common, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]},
                                  {**common, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, **tool}]}, 'finish_reason': None}]},
                                  {**common, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}]
                    else:
                        chunks = [{**common, 'object': 'chat.completion', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': None, 'tool_calls': [tool]}, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}]
                else:
                    result = {'id': 'resp_test', 'object': 'response', 'created_at': 1, 'model': 'gpt-4o-mini', 'status': 'completed', 'output': [{'type': 'function_call', 'id': 'fc_test', 'call_id': 'call_test', 'name': 'write_file', 'arguments': '{"path":"out.txt"}', 'status': 'completed'}], 'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}, 'parallel_tool_calls': False, 'tool_choice': 'auto', 'tools': [], 'temperature': 1, 'top_p': 1, 'error': None, 'incomplete_details': None, 'instructions': None, 'metadata': {}}
                    chunks = [{'type': 'response.created', 'sequence_number': 0, 'response': {**result, 'status': 'in_progress', 'output': []}}, {'type': 'response.output_item.added', 'sequence_number': 1, 'output_index': 0, 'item': {**result['output'][0], 'arguments': '', 'status': 'in_progress'}}, {'type': 'response.function_call_arguments.delta', 'sequence_number': 2, 'item_id': 'fc_test', 'output_index': 0, 'delta': '{"path":"out.txt"}'}, {'type': 'response.function_call_arguments.done', 'sequence_number': 3, 'item_id': 'fc_test', 'output_index': 0, 'arguments': '{"path":"out.txt"}'}, {'type': 'response.output_item.done', 'sequence_number': 4, 'output_index': 0, 'item': result['output'][0]}, {'type': 'response.completed', 'sequence_number': 5, 'response': result}] if body.get('stream') else [result]
                for chunk in chunks:
                    data = ('data: ' + json.dumps(chunk) + '\n\n') if body.get('stream') else json.dumps(chunk)
                    self.wfile.write(data.encode()); self.wfile.flush()
                if body.get('stream') and self.path.endswith('/chat/completions'):
                    self.wfile.write(b'data: [DONE]\n\n')
                self.close_connection = True
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            model = {'id': 'gpt-4o-mini', 'input_per_million': 1, 'output_per_million': 2, 'context_window': 1000, 'capabilities': ['tools']}
            provider = Provider('test', f'http://127.0.0.1:{server.server_port}/v1', 'fake')
            for endpoint in ('/v1/messages', '/v1/responses'):
                for stream in (False, True):
                    gateway = Gateway(provider, model, Budget(1, 30))
                    tool = {'name': 'write_file', 'description': 'Write a file', 'input_schema': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}
                    body = {'model': model['id'], 'stream': stream}
                    if endpoint.endswith('messages'):
                        body.update(messages=[{'role': 'user', 'content': 'Write a file'}], tools=[tool], max_tokens=20)
                    else:
                        body.update(input='Write a file', client_metadata={'source':'codex'}, tools=[{'type':'tool_search','execution':'client'},{'type':'custom','name':'apply_patch','description':'Apply a patch','format':{'type':'text'}},{'type': 'function', 'name': tool['name'], 'description': tool['description'], 'parameters': tool['input_schema']}], max_output_tokens=20)
                    chunks = []
                    result = asyncio.run(gateway.execute(endpoint, body, chunks.append))
                    self.assertAlmostEqual(gateway.cost, .00002, msg=str(gateway.records))
                    self.assertIn('write_file', json.dumps(chunks if stream else result))
            self.assertEqual(len(requests), 4)
            self.assertTrue(all(body.get('tools') for _, body in requests))
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_native_anthropic_preserves_reasoning(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        captured=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.path,dict(self.headers),body))
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'id':'msg_test','type':'message','role':'assistant','content':[{'type':'text','text':'hello'}],'usage':{'input_tokens':5,'output_tokens':2}}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            model={'id':'unknown-adaptive-model','litellm_model':'anthropic/unknown-adaptive-model','input_per_million':1,'output_per_million':2,'context_window':1000,'efforts':['low']}
            gateway=Gateway(Provider('test',f'http://127.0.0.1:{server.server_port}/v1','fake'),model,Budget(1,10))
            body={'model':model['id'],'messages':[{'role':'user','content':'hi'}],'max_tokens':50,'thinking':{'type':'adaptive'},'output_config':{'effort':'low'},'temperature':1,'context_management':{'edits':[]}}
            asyncio.run(gateway.execute('/v1/messages?beta=true',body,headers={'anthropic-beta':'test-beta'}))
            self.assertEqual(captured[0][0],'/v1/messages')
            self.assertEqual(captured[0][2],body)
            self.assertEqual(captured[0][1]['anthropic-beta'],'test-beta')
        finally:
            server.shutdown();server.server_close();thread.join()
