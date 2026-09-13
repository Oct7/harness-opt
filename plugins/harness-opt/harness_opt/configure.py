"""Create provider configuration without putting credentials in arguments or output."""
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile

from dotenv import dotenv_values, set_key

from .providers import validate_provider_url


def configure(provider, env_file, base_url=None, api_key_env=None, prompt_key=False):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', provider):
        raise ValueError('Provider name must use letters, digits and underscores')
    path = Path(env_file).expanduser().absolute()
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError('Configuration destination must be a regular file')
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Store credentials outside the installed plugin/package directory')
    existing = dotenv_values(path, interpolate=False)
    prefix = 'HARNESS_' + provider.upper()
    url_key, key_key = prefix + '_BASE_URL', prefix + '_API_KEY'
    presets = {'openrouter': 'https://openrouter.ai/api/v1', 'ollama': 'http://127.0.0.1:11434/v1'}
    url = base_url or os.environ.get(url_key) or existing.get(url_key) or presets.get(provider.lower())
    if not url:
        raise ValueError('A custom provider requires --base-url')
    validate_provider_url(url, provider)
    if api_key_env and prompt_key:
        raise ValueError('Choose --api-key-env or --prompt-key')
    updates = {url_key: url.rstrip('/')}
    secret = existing.get(key_key) or ''
    if api_key_env:
        secret = os.environ.get(api_key_env)
        if not secret:
            raise ValueError('The named API key environment variable is empty or missing')
        updates[key_key] = secret
    elif prompt_key:
        if not sys.stdin.isatty():
            raise ValueError('Use --prompt-key in an interactive terminal, or use --api-key-env')
        secret = getpass.getpass('API key (hidden): ')
        if not secret:
            raise ValueError('API key must not be empty')
        updates[key_key] = secret
    elif key_key not in existing and not os.environ.get(key_key):
        # Ollama's compatibility API requires a placeholder, not a service credential.
        secret = 'ollama' if provider.lower() == 'ollama' else ''
        updates[key_key] = secret
    effective_secret = os.environ.get(key_key, secret)
    if any(character in value for value in (secret, effective_secret) for character in ('\n', '\r', '\0')):
        raise ValueError('API key must be a single line')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.harness-env-', delete=False) as output:
            staged = Path(output.name)
            output.write(path.read_text() if path.exists() else '# harness-opt provider configuration\n')
        for key, value in updates.items():
            set_key(staged, key, value)
        staged.chmod(0o600)
        os.replace(staged, path)
    finally:
        if staged:
            staged.unlink(missing_ok=True)
    return {'status': 'configured' if effective_secret else 'needs_api_key',
            'provider': provider.lower(), 'base_url': url.rstrip('/'), 'env_file': str(path),
            'api_key_variable': key_key, 'environment_overrides_key': key_key in os.environ,
            'connection_verified': False}
