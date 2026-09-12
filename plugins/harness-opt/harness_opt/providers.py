"""Provider discovery. Missing metadata is unknown, never invented."""
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class DiscoveryError(RuntimeError):
    def __init__(self, category, message):
        self.category = category
        super().__init__(message)


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str = field(repr=False)
    models: list = field(default_factory=list)


def load_providers(env_file='.env'):
    values = {}
    path = Path(env_file or '.env')
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.removeprefix('export ').partition('=')
            if sep:
                values[key.strip()] = value.strip().strip('\"\'')
    values.update(os.environ)
    result = {}
    for key, url in values.items():
        match = re.fullmatch(r'HARNESS_(.+)_BASE_URL', key)
        if not match:
            continue
        name = match[1]
        secret = values.get(f'HARNESS_{name}_API_KEY')
        if not secret:
            raise ValueError(f'Missing HARNESS_{name}_API_KEY')
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError(f'Invalid provider URL for {name}')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote provider URLs must use HTTPS')
        models = json.loads(values.get(f'HARNESS_{name}_MODELS', '[]'))
        if not isinstance(models, list):
            raise ValueError(f'HARNESS_{name}_MODELS must be a JSON list')
        result[name.lower()] = Provider(name.lower(), url.rstrip('/'), secret, models)
    return result


def _rate(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def normalize_model(raw, provider, verified=False):
    if isinstance(raw, str):
        raw = {'id': raw}
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id'].strip():
        raise DiscoveryError('schema', 'Models require a nonempty string id')
    pricing = raw.get('pricing') or {}
    if not isinstance(pricing, dict):
        raise DiscoveryError('schema', 'Model pricing must be an object')
    def price(kind):
        explicit = raw.get(kind + '_per_million')
        if explicit is not None:
            return _rate(explicit)
        rate = _rate(pricing.get('prompt' if kind == 'input' else 'completion'))
        return rate * 1_000_000 if rate is not None else None
    adapter = 'anthropic' if urlparse(provider.base_url).hostname == 'api.anthropic.com' else 'openai'
    return {**raw, 'litellm_model': raw.get('litellm_model', adapter + '/' + raw['id']),
            'source': raw.get('source', provider.base_url + '/models'), 'checked_date': date.today().isoformat(),
            'id': raw['id'], 'provider': provider.name, 'verified': verified,
            'input_per_million': price('input'), 'output_per_million': price('output'),
            'capabilities': raw.get('capabilities', raw.get('supported_parameters', [])),
            'efforts': raw.get('efforts', (raw.get('reasoning') or {}).get('supported_efforts', [])),
            'max_output_tokens': raw.get('max_output_tokens', (raw.get('top_provider') or {}).get('max_completion_tokens')),
            'cache_read_per_million': raw.get('cache_read_per_million', _rate(pricing.get('input_cache_read')) * 1_000_000 if _rate(pricing.get('input_cache_read')) is not None else None),
            'cache_write_per_million': raw.get('cache_write_per_million', _rate(pricing.get('input_cache_write')) * 1_000_000 if _rate(pricing.get('input_cache_write')) is not None else None),
            'price_checked_at': date.today().isoformat(),
            'model_version': raw.get('model_version', raw.get('canonical_slug')),
            'context_window': raw.get('context_window', raw.get('context_length', raw.get('max_input_tokens'))),
            'price_source': raw.get('price_source', provider.base_url + '/models' if pricing else 'user' if raw.get('input_per_million') is not None else None)}


def discover_models(provider):
    headers = {'Authorization': 'Bearer ' + provider.api_key} if provider.api_key else {}
    if urlparse(provider.base_url).hostname == 'api.anthropic.com':
        headers = {'x-api-key': provider.api_key, 'anthropic-version': '2023-06-01'}
    request = Request(provider.base_url + '/models', headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise DiscoveryError('schema', 'Model catalog must be an object')
        rows = data.get('data', data.get('models', []))
        if not isinstance(rows, list):
            raise DiscoveryError('schema', 'Invalid model list')
        result = [normalize_model(row, provider) for row in rows]
    except HTTPError as error:
        if error.code not in (404, 405, 501):
            raise DiscoveryError('authentication' if error.code in (401, 403) else 'transport', f'Provider model discovery HTTP {error.code}') from None
        result = []
        if urlparse(provider.base_url).hostname == 'api.anthropic.com':
            result = [normalize_model({'id': model, 'source': 'https://platform.claude.com/docs/en/models/overview'}, provider)
                      for model in ('claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5-20251001')]
    overrides = {row['id']: row for row in result}
    for row in provider.models:
        row = {'id': row} if isinstance(row, str) else row
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise DiscoveryError('schema', 'Configured models require a string id')
        normalized = normalize_model({**overrides.get(row['id'], {}), **row}, provider)
        overrides[normalized['id']] = normalized
    if not overrides:
        raise ValueError(f'No model list available; set HARNESS_{provider.name.upper()}_MODELS to a JSON model list')
    provider.models = list(overrides.values())
    return provider.models


def load_openrouter_catalog():
    return discover_models(Provider('openrouter', 'https://openrouter.ai/api/v1', ''))


def tier_model(model, input_tokens):
    pricing = model.get('pricing') or {}
    tiers = pricing.get('overrides') or []
    if not isinstance(tiers, list):
        raise ValueError('Invalid pricing tiers')
    selected = dict(model)
    for tier in sorted(tiers, key=lambda row: float(row.get('min_prompt_tokens', 0))):
        threshold = _rate(tier.get('min_prompt_tokens'))
        if threshold is None:
            raise ValueError('Invalid pricing tier threshold')
        if input_tokens >= threshold:
            for api_key, key in (('prompt', 'input_per_million'), ('completion', 'output_per_million'),
                                 ('input_cache_read', 'cache_read_per_million'), ('input_cache_write', 'cache_write_per_million')):
                if api_key in tier:
                    value = _rate(tier[api_key])
                    if value is None:
                        raise ValueError('Invalid tier rate')
                    selected[key] = value * 1_000_000
    return selected


def usage_cost(usage, model):
    """Reasoning tokens are already inside output totals; cache is format-specific."""
    if usage.get('cost') is not None:
        return _rate(usage['cost']), 'provider'
    token_count = _rate(usage.get('input_tokens', usage.get('prompt_tokens')))
    if token_count is None:
        return None, 'unknown'
    for key in ('cache_read_input_tokens', 'cache_creation_input_tokens'):
        count = _rate(usage.get(key, 0))
        if count is None:
            return None, 'unknown'
        token_count += count
    try:
        model = tier_model(model, token_count)
    except (TypeError, ValueError):
        return None, 'unknown'
    inp, out = model.get('input_per_million'), model.get('output_per_million')
    if inp is None or out is None or not usage:
        return None, 'unknown'
    inp, out = _rate(inp), _rate(out)
    if inp is None or out is None:
        return None, 'unknown'
    inputs = _rate(usage.get('input_tokens', usage.get('prompt_tokens')))
    outputs = _rate(usage.get('output_tokens', usage.get('completion_tokens')))
    if inputs is None or outputs is None or _rate(inputs) is None or _rate(outputs) is None:
        return None, 'unknown'
    details = usage.get('input_tokens_details', usage.get('prompt_tokens_details', {})) or {}
    if not isinstance(details, dict):
        return None, 'unknown'
    cached = _rate(details.get('cached_tokens', 0))
    read = _rate(usage.get('cache_read_input_tokens', 0))
    creation = _rate(usage.get('cache_creation_input_tokens', 0))
    if (cached or read) and model.get('cache_read_per_million') is None or creation and model.get('cache_write_per_million') is None:
        return None, 'unknown'
    if any(_rate(v) is None for v in (cached, read, creation)) or cached > inputs:
        return None, 'unknown'
    cost = (inputs - cached) * inp + outputs * out
    read_rate = _rate(model.get('cache_read_per_million') or 0)
    write_rate = _rate(model.get('cache_write_per_million') or 0)
    if read_rate is None or write_rate is None:
        return None, 'unknown'
    cost += (cached + read) * read_rate
    creation_details = usage.get('cache_creation') or {}
    if creation_details:
        if not isinstance(creation_details, dict):
            return None, 'unknown'
        detailed = 0
        for duration, count in creation_details.items():
            count = _rate(count)
            rate = _rate(model.get('cache_write_' + duration.removesuffix('_input_tokens') + '_per_million'))
            if count is None or count and rate is None:
                return None, 'unknown'
            detailed += count
            cost += count * (rate or 0)
        if detailed != creation:
            return None, 'unknown'
    else:
        cost += creation * write_rate
    return cost / 1_000_000, 'usage_estimate'
