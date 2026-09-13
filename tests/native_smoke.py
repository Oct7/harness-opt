"""Opt-in offline native CLI -> metered gateway -> loopback provider smoke.

Run: PYTHONPATH=plugins/harness-opt .venv/bin/python tests/native_smoke.py
Checks explicit API gateway and current native configuration paths.
No production credentials or native user settings are loaded.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from harness_opt.budget import Budget
from harness_opt.gateway import Gateway
from harness_opt.providers import Provider
from harness_opt.runner import capture_profile, execute


def main():
    captured = []
    tool_phase = False
    tool_sent = False
    active_work = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            nonlocal tool_sent
            send_tool = tool_phase and not tool_sent
            tool_sent = tool_sent or send_tool
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append({'path': self.path, 'model': body.get('model'), 'fields': sorted(body),
                             'tools': [tool.get('name') for tool in body.get('tools', [])]})
            if '/messages' in self.path:
                response = {'id': 'msg_smoke', 'type': 'message', 'role': 'assistant',
                            'model': body['model'], 'content': [], 'stop_reason': None,
                            'stop_sequence': None, 'usage': {'input_tokens': 20, 'output_tokens': 0,
                            'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}}
                events = [
                    {'type': 'message_start', 'message': response},
                    {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'OFFLINE_SMOKE_OK'}},
                    {'type': 'content_block_stop', 'index': 0},
                    {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 4}},
                    {'type': 'message_stop'},
                ]
            else:
                message = {'id': 'msg_smoke', 'type': 'message', 'status': 'completed', 'role': 'assistant',
                           'content': [{'type': 'output_text', 'text': 'OFFLINE_SMOKE_OK', 'annotations': []}]}
                response = {'id': 'resp_smoke', 'object': 'response', 'created_at': 1, 'status': 'in_progress',
                            'model': body['model'], 'output': [], 'parallel_tool_calls': True,
                            'tool_choice': 'auto', 'tools': [], 'error': None, 'incomplete_details': None}
                events = [
                    {'type': 'response.created', 'response': dict(response)},
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': {**message, 'status': 'in_progress', 'content': []}},
                    {'type': 'response.content_part.added', 'item_id': 'msg_smoke', 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': '', 'annotations': []}},
                    {'type': 'response.output_text.delta', 'item_id': 'msg_smoke', 'output_index': 0, 'content_index': 0, 'delta': 'OFFLINE_SMOKE_OK'},
                    {'type': 'response.output_text.done', 'item_id': 'msg_smoke', 'output_index': 0, 'content_index': 0, 'text': 'OFFLINE_SMOKE_OK'},
                    {'type': 'response.content_part.done', 'item_id': 'msg_smoke', 'output_index': 0, 'content_index': 0, 'part': message['content'][0]},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': message},
                    {'type': 'response.completed', 'response': {**response, 'status': 'completed', 'output': [message],
                     'usage': {'input_tokens': 20, 'output_tokens': 4, 'total_tokens': 24,
                               'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}},
                ]
                for sequence, event in enumerate(events):
                    event['sequence_number'] = sequence
            if send_tool and '/messages' in self.path:
                arguments = {'file_path': str(active_work / 'smoke.txt'), 'content': 'OFFLINE_TOOL_OK'}
                events = [
                    {'type': 'message_start', 'message': response},
                    {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'tool_use', 'id': 'tool_smoke', 'name': 'Write', 'input': {}}},
                    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(arguments)}},
                    {'type': 'content_block_stop', 'index': 0},
                    {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use', 'stop_sequence': None}, 'usage': {'output_tokens': 10}},
                    {'type': 'message_stop'},
                ]
            elif send_tool:
                arguments = json.dumps({'cmd': 'printf OFFLINE_TOOL_OK > smoke.txt', 'yield_time_ms': 1000, 'max_output_tokens': 100})
                call = {'type': 'function_call', 'id': 'fc_smoke', 'call_id': 'call_smoke', 'name': 'exec_command', 'arguments': arguments, 'status': 'completed'}
                events = [
                    {'type': 'response.created', 'response': dict(response)},
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': {**call, 'status': 'in_progress', 'arguments': ''}},
                    {'type': 'response.function_call_arguments.delta', 'item_id': 'fc_smoke', 'output_index': 0, 'delta': arguments},
                    {'type': 'response.function_call_arguments.done', 'item_id': 'fc_smoke', 'output_index': 0, 'arguments': arguments},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': call},
                    {'type': 'response.completed', 'response': {**response, 'status': 'completed', 'output': [call],
                     'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30,
                               'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}},
                ]
                for sequence, event in enumerate(events):
                    event['sequence_number'] = sequence
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for event in events:
                self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='harness-native-smoke-') as temp:
            root = Path(temp)
            home = root / 'home'
            home.mkdir()
            (home / '.codex').mkdir()
            (home / '.claude').mkdir()
            (home / '.claude/settings.json').write_text(json.dumps({'permissions': {'allow': ['Write']}}))
            (home / '.codex/config.toml').write_text('web_search="disabled"\nsandbox_mode="workspace-write"\napproval_policy="never"\n[features]\nskill_search=false\ntool_suggest=false\n')
            source = root / 'source'
            source.mkdir()
            env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
                   'CODEX_HOME': str(home / '.codex'), 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                   'DISABLE_AUTOUPDATER': '1', 'DISABLE_TELEMETRY': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True'}
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, env, clear=True):
                for runner, model_id, adapter in [('claude', 'claude-sonnet-4-6', 'anthropic'), ('codex', 'gpt-5.4', 'openai')]:
                    if not shutil.which(runner):
                        raise RuntimeError(f'{runner} is required for native smoke')
                    model = {'id': model_id, 'litellm_model': adapter + '/' + model_id,
                             'input_per_million': 0, 'output_per_million': 0,
                             'cache_read_per_million': 0, 'cache_write_per_million': 0,
                             'context_window': 1000000, 'efforts': ['high'], 'capabilities': ['tools']}
                    provider = Provider('offline', f'http://127.0.0.1:{server.server_port}/v1', 'offline-provider-key', [model])
                    profile = capture_profile(runner, source, model=model_id, effort='high')
                    for scenario in ('text', 'file-tool'):
                        tool_phase, tool_sent = scenario == 'file-tool', False
                        work = root / (runner + '-' + scenario)
                        work.mkdir()
                        active_work = work
                        with Gateway(provider, model, Budget(1, 30), effort='high') as gateway:
                            result = execute(dict(profile, gateway_api_key=gateway.api_key), work, ('Create smoke.txt containing OFFLINE_TOOL_OK, then say OFFLINE_SMOKE_OK.' if tool_phase else 'Say OFFLINE_SMOKE_OK.'), gateway.base_url, 25)
                        print(json.dumps({'runner': runner, 'scenario': scenario, 'version': profile['version'], 'status': result['status'],
                                          'call_count': len(gateway.records), 'usage': [record.get('usage') for record in gateway.records],
                                          'measured_ttft': all(record.get('ttft') is not None for record in gateway.records)}))
                        assert result['status'] == 'completed', result
                        assert 'OFFLINE_SMOKE_OK' in result['output'], result
                        assert gateway.records and all(record.get('usage') for record in gateway.records), gateway.records
                        assert all(record['cost'] == 0 for record in gateway.records), gateway.records
                        if tool_phase:
                            assert (work / 'smoke.txt').read_text() == 'OFFLINE_TOOL_OK', result
                            assert len(gateway.records) >= 2, gateway.records
                    # Existing native provider configuration: no harness gateway or HARNESS key.
                    if runner == 'claude':
                        os.environ.update(ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}',
                                          ANTHROPIC_API_KEY='offline-provider-key', ANTHROPIC_MODEL=model_id,
                                          CLAUDE_CODE_EFFORT_LEVEL='high')
                    else:
                        config_path = home / '.codex/config.toml'
                        config_path.write_text('model="' + model_id + '"\nmodel_reasoning_effort="high"\nmodel_provider="offline"\n' + config_path.read_text() +
                                               '\n[model_providers.offline]\nname="Offline native fixture"\nbase_url="http://127.0.0.1:' + str(server.server_port) +
                                               '/v1"\nwire_api="responses"\nenv_key="OPENAI_API_KEY"\n')
                        os.environ['OPENAI_API_KEY'] = 'offline-provider-key'
                    profile = capture_profile(runner, source, current=True)
                    for scenario in ('text', 'file-tool'):
                        tool_phase, tool_sent = scenario == 'file-tool', False
                        work = root / (runner + '-current-' + scenario)
                        work.mkdir()
                        active_work = work
                        previous_requests = len(captured)
                        assert not any(name.startswith('HARNESS_') for name in os.environ)
                        result = execute(profile, work, ('Create smoke.txt containing OFFLINE_TOOL_OK, then say OFFLINE_SMOKE_OK.' if tool_phase else 'Say OFFLINE_SMOKE_OK.'), None, 25)
                        assert result['status'] == 'completed', result
                        assert 'OFFLINE_SMOKE_OK' in result['output'], result
                        assert result['usage_source'] == 'native_runner', result
                        expected_input, expected_output = (40, 14) if tool_phase else (20, 4)
                        assert result['usage']['input_tokens'] == expected_input, result
                        assert result['usage']['output_tokens'] == expected_output, result
                        assert len(captured) - previous_requests == (2 if tool_phase else 1), captured
                        if tool_phase:
                            assert (work / 'smoke.txt').read_text() == 'OFFLINE_TOOL_OK', result
                        print(json.dumps({'runner': runner, 'execution': 'current', 'scenario': scenario,
                                          'status': result['status'], 'usage_source': result['usage_source'],
                                          'input_tokens': result['usage']['input_tokens'], 'output_tokens': result['usage']['output_tokens']}))
            print(json.dumps({'provider_request_count': len(captured), 'protocols': sorted({request['path'] for request in captured})}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
