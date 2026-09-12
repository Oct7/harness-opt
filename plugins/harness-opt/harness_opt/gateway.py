"""Loopback gateway retaining LiteLLM's native Messages/Responses adapters."""
import asyncio
import codecs
import importlib.metadata
import json
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .budget import BudgetExceeded
from .providers import usage_cost, _rate, tier_model


class CompatibilityError(RuntimeError):
    pass


def _dict(value):
    return value if isinstance(value, dict) else value.model_dump(exclude_none=True)


async def _stream_chunks(response):
    pending = ''
    decoder = codecs.getincrementaldecoder('utf-8')()
    async for item in response:
        if isinstance(item, (bytes, str)):
            pending += decoder.decode(item) if isinstance(item, bytes) else item
            pending = pending.replace('\r\n', '\n')
            while '\n\n' in pending:
                event, pending = pending.split('\n\n', 1)
                data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
                if data and data != '[DONE]':
                    yield json.loads(data)
        else:
            yield _dict(item)
    pending += decoder.decode(b'', final=True)
    if pending.strip():
        raise CompatibilityError('Truncated SSE frame')


async def _native_request(payload, provider, timeout, headers, messages=True):
    """Same-format requests need no LiteLLM transformation (which can drop fields)."""
    import httpx
    payload = dict(payload)
    payload['model'] = payload['model'].removeprefix('anthropic/' if messages else 'openai/')
    root = provider.base_url.rstrip('/')
    url = root + ('/messages' if root.endswith('/v1') else '/v1/messages') if messages else root + '/responses'
    headers = ({'x-api-key': provider.api_key, 'anthropic-version': '2023-06-01', **headers} if messages else {'Authorization': 'Bearer ' + provider.api_key, **headers})
    if payload.get('stream'):
        async def stream():
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream('POST', url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        return stream()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


class Gateway:
    def __init__(self, provider, model, budget, effort=None):
        self.provider, self.model, self.budget, self.effort = provider, model, budget, effort
        self.records, self.compatibility_errors = [], []
        self.api_key = secrets.token_urlsafe(32)
        self.models = {m['id']: m for m in provider.models if isinstance(m, dict)}
        self.models[model['id']] = model
        self.aliases = set(model.get('runner_aliases', []))
        try:
            self.version = importlib.metadata.version('litellm')
        except importlib.metadata.PackageNotFoundError:
            self.version = 'not-installed'

    @property
    def cost(self):
        costs = [r.get('cost') for r in self.records if r.get('dispatched')]
        return None if any(v is None for v in costs) else sum(costs)

    async def execute(self, path, body, emit=None, headers=None):
        started = time.monotonic()
        parsed_path = urlsplit(path)
        query = parse_qs(parsed_path.query)
        path = parsed_path.path
        record = {'endpoint': path, 'model': body.get('model'), 'cost': None, 'dispatched': False,
                  'ttft': None, 'gateway_version': self.version, 'transformations': []}
        self.records.append(record)
        reservation = None
        try:
            if query and query != {'beta': ['true']}:
                raise CompatibilityError('Unsupported gateway query')
            if path not in ('/v1/messages', '/v1/responses', '/responses'):
                raise CompatibilityError('Unsupported gateway endpoint')
            allowed = ({'model', 'messages', 'max_tokens', 'metadata', 'stop_sequences', 'stream', 'system', 'temperature', 'thinking', 'tool_choice', 'tools', 'top_k', 'top_p', 'output_config', 'context_management'}
                       if path == '/v1/messages' else
                       {'model', 'input', 'instructions', 'max_output_tokens', 'metadata', 'parallel_tool_calls', 'previous_response_id', 'reasoning', 'store', 'stream', 'temperature', 'text', 'tool_choice', 'tools', 'top_p', 'truncation', 'include', 'user', 'service_tier', 'prompt_cache_key', 'safety_identifier', 'client_metadata'})
            if set(body) - allowed:
                raise CompatibilityError('Unverified request fields: ' + ', '.join(sorted(set(body) - allowed)))
            if body.get('service_tier') not in (None, 'default'):
                raise CompatibilityError('Non-default service tier pricing is unverified')
            requested = body.get('model')
            selected = self.model if requested == self.model['id'] or requested in self.aliases else self.models.get(requested)
            if not selected:
                raise CompatibilityError('Unpriced fixed subagent model: ' + str(requested))
            adapter = selected.get('litellm_model', 'openai/' + selected['id']).split('/')[0]
            if adapter != 'anthropic' and body.get('context_management'):
                raise CompatibilityError('Anthropic context_management conversion is unverified')
            capabilities = selected.get('capabilities') or []
            if body.get('tools'):
                if not any(cap in capabilities for cap in ('tools', 'tool_calling', 'function_calling')):
                    raise CompatibilityError('Tool capability unverified')
                for tool in body['tools']:
                    if isinstance(tool, dict) and tool.get('type') == 'tool_search' and tool.get('execution') == 'client' and adapter == 'openai' and path != '/v1/messages':
                        continue
                    if not isinstance(tool, dict) or tool.get('type', 'custom') not in ('function', 'custom'):
                        raise CompatibilityError('Hosted tools have unbounded non-token charges')
                    if path != '/v1/messages' and tool.get('type') != 'function' and adapter != 'openai':
                        raise CompatibilityError('Only function tools verified across Responses adapters')
            extras = selected.get('pricing') or {}
            if any(_rate(value) != 0 for key, value in extras.items()
                   if key not in ('prompt', 'completion', 'input_cache_read', 'input_cache_write', 'overrides', 'web_search', 'image')):
                raise CompatibilityError('Non-token pricing is not bounded')
            def has_media(value):
                if isinstance(value, dict):
                    if value.get('type') in ('image', 'image_url', 'input_image', 'input_audio', 'audio', 'file', 'input_file', 'document', 'video'):
                        return True
                    return any(has_media(item) for item in value.values())
                return isinstance(value, list) and any(has_media(item) for item in value)
            def validate_cache(value):
                if isinstance(value, dict):
                    control = value.get('cache_control')
                    if control:
                        if not isinstance(control, dict) or control.get('type') != 'ephemeral':
                            raise BudgetExceeded('Unverified cache billing control')
                        key = 'cache_write_ephemeral_1h_per_million' if control.get('ttl') == '1h' else 'cache_write_per_million'
                        if _rate(selected.get(key)) is None:
                            raise BudgetExceeded('Cache creation price required before dispatch')
                    for item in value.values():
                        validate_cache(item)
                elif isinstance(value, list):
                    for item in value:
                        validate_cache(item)
            validate_cache(body)
            if has_media(body):
                raise CompatibilityError('Media billing bounds are unverified')
            effort = self.effort if selected is self.model else None
            native_effort = (body.get('reasoning') or {}).get('effort') or (body.get('output_config') or {}).get('effort')
            if (effort or native_effort) and (effort or native_effort) not in selected.get('efforts', []):
                raise CompatibilityError('Unsupported or unverified effort')
            if path == '/v1/messages' and adapter != 'anthropic' and (effort or native_effort or body.get('thinking') or body.get('top_k')):
                raise CompatibilityError('Anthropic reasoning/top_k conversion is unverified for this adapter')
            if path != '/v1/messages' and adapter != 'openai':
                lossy = {'client_metadata', 'previous_response_id', 'include', 'store', 'text', 'reasoning', 'truncation'}
                if lossy.intersection(body) or effort:
                    raise CompatibilityError('Responses state/reasoning conversion is unverified for this adapter')
            context = _rate(selected.get('context_window'))
            rates = [_rate(selected.get('input_per_million')), _rate(selected.get('output_per_million'))]
            if not context or any(rate is None for rate in rates):
                raise BudgetExceeded('Context limit and prices required for safe reservation')
            # Reserve the whole context at the largest token rate, including cache writes.
            cache_rates = [_rate(selected.get(key) or 0) for key in ('cache_write_per_million', 'cache_read_per_million')]
            if any(rate is None for rate in cache_rates):
                raise BudgetExceeded('Invalid cache pricing')
            tier_rates = []
            for tier in (selected.get('pricing') or {}).get('overrides', []):
                priced = tier_model(selected, tier['min_prompt_tokens'])
                tier_rates.extend(_rate(priced.get(key) or 0) for key in ('input_per_million', 'output_per_million', 'cache_read_per_million', 'cache_write_per_million'))
            duration_rates = [_rate(value) for key, value in selected.items() if key.startswith('cache_write_') and key.endswith('_per_million') and value is not None]
            if any(rate is None for rate in duration_rates):
                raise BudgetExceeded('Invalid cache duration pricing')
            max_rate = max(rates + cache_rates + tier_rates + duration_rates)
            output_bound = _rate(body.get('max_tokens', body.get('max_output_tokens', selected.get('max_output_tokens') or context)))
            if output_bound is None:
                raise BudgetExceeded('Invalid output token limit')
            reservation = self.budget.reserve((context + output_bound) * max_rate / 1_000_000)
            payload = dict(body)
            payload['model'] = selected.get('litellm_model', 'openai/' + selected['id'])
            record['model'] = selected['id']
            record['transformations'].append({'field': 'model', 'from': requested, 'to': payload['model']})
            if effort:
                field = 'output_config' if path == '/v1/messages' else 'reasoning'
                payload[field] = {**payload.get(field, {}), 'effort': effort}
                record['transformations'].append({'field': field + '.effort', 'to': effort})
            # User payload must never override credentials, transport, retries, or field validation.
            prohibited = {'api_key', 'api_base', 'base_url', 'drop_params', 'num_retries', 'timeout', 'custom_llm_provider'}
            if prohibited.intersection(payload):
                raise CompatibilityError('Request contains reserved gateway settings')
            import litellm
            litellm.drop_params = False
            call = litellm.anthropic.messages.acreate if path == '/v1/messages' else litellm.aresponses
            transport = {}
            if headers:
                if adapter != 'anthropic' and headers.get('anthropic-beta'):
                    raise CompatibilityError('Anthropic beta header conversion is unverified')
                if adapter == 'anthropic':
                    transport['extra_headers'] = {key: value for key, value in headers.items() if key in ('anthropic-beta', 'anthropic-version')}
            record['dispatched'] = True
            if path == '/v1/messages' and adapter == 'anthropic' or path != '/v1/messages' and adapter == 'openai':
                record['transport'] = 'native_' + adapter + '_passthrough'
                response = await _native_request(payload, self.provider, max(.001, self.budget.time_left), transport.get('extra_headers', {}), messages=path == '/v1/messages')
            else:
                record['transport'] = 'litellm'
                response = await call(**payload, api_key=self.provider.api_key, api_base=self.provider.base_url,
                                      num_retries=0, timeout=max(0.001, self.budget.time_left), drop_params=False, **transport)
            usage = {}
            result = None
            if body.get('stream'):
                completed = False
                async for chunk in _stream_chunks(response):
                    kind = chunk.get('type', '')
                    completed = completed or kind in ('message_stop', 'response.completed')
                    delta = chunk.get('delta') or {}
                    if record['ttft'] is None and (isinstance(delta, dict) and (delta.get('text') or delta.get('partial_json')) or kind in ('response.output_text.delta', 'response.function_call_arguments.delta') and chunk.get('delta')):
                        record['ttft'] = time.monotonic() - started
                    for source in (chunk, chunk.get('message') or {}, chunk.get('response') or {}):
                        if source.get('usage'):
                            usage.update(source['usage'])
                    if emit:
                        emit(chunk)
                if not completed:
                    raise CompatibilityError('Stream ended without completion event')
            else:
                result = _dict(response)
                usage = result.get('usage') or {}
            record['usage'] = usage
            record['cost'], record['cost_source'] = usage_cost(usage, selected)
            self.budget.settle(reservation, record['cost'])
            reservation = None
            selected['verified'] = True
            return result
        except BaseException as error:
            status_code = getattr(getattr(error, 'response', None), 'status_code', None)
            category = 'budget' if isinstance(error, BudgetExceeded) else 'compatibility' if isinstance(error, CompatibilityError) or type(error).__name__ in ('UnsupportedParamsError', 'BadRequestError') else 'authentication' if type(error).__name__ == 'AuthenticationError' or status_code in (401, 403) else 'transport'
            record['error'] = category
            # Exception strings may contain upstream URLs, headers or credentials.
            record['error_type'] = type(error).__name__
            if category == 'compatibility':
                self.compatibility_errors.append({'model': record['model'], 'error_type': type(error).__name__})
            raise
        finally:
            if reservation:
                self.budget.settle(reservation, None if record['dispatched'] else 0)
            record['duration'] = time.monotonic() - started
            output = record.get('usage', {}).get('output_tokens')
            record['tps'] = output / record['duration'] if output is not None and record['duration'] else None

    def __enter__(self):
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                auth = self.headers.get('Authorization', '').removeprefix('Bearer ') or self.headers.get('x-api-key', '')
                if not secrets.compare_digest(auth, gateway.api_key):
                    self.send_error(401)
                    return
                streaming = False
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 16 * 1024 * 1024:
                        raise CompatibilityError('Invalid request size')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise CompatibilityError('Request must be an object')
                    def emit(chunk):
                        nonlocal streaming
                        if not streaming:
                            self.send_response(200)
                            self.send_header('Content-Type', 'text/event-stream')
                            self.end_headers()
                            streaming = True
                        event = chunk.get('type')
                        if event:
                            self.wfile.write(('event: ' + event + '\n').encode())
                        self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                        self.wfile.flush()
                    result = asyncio.run(asyncio.wait_for(gateway.execute(self.path, body, emit, {key.lower(): value for key, value in self.headers.items() if key.lower() in ('anthropic-beta', 'anthropic-version')}), timeout=max(.001, gateway.budget.time_left)))
                    if not streaming:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(result).encode())
                except Exception as error:
                    if not streaming:
                        self.send_response(429 if isinstance(error, BudgetExceeded) else 400 if isinstance(error, CompatibilityError) else 502)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'error': {'type': type(error).__name__, 'message': 'Gateway rejected or failed request; see local telemetry'}}).encode())
                self.close_connection = True
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base_url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
