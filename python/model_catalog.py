"""Public model discovery and version-compatible local Codex catalogs."""
import copy
import json
import os
import pathlib
import re
import tempfile
import urllib.error
import urllib.request
import quota_status as quota

from provider_key import read_key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def valid_model(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and not any(c.isspace() or ord(c) < 32 for c in value)


def model_ids(values, default):
    if values is None: return [default]
    if not isinstance(values, list) or len(values) > 250 or any(not valid_model(v) for v in values):
        raise ValueError('可选模型应为不超过 250 个有效模型 ID。')
    return list(dict.fromkeys([default] + values))


def load_entries(path):
    try:
        document = json.loads(pathlib.Path(path).expanduser().read_text(encoding='utf-8-sig'))
        return [e for e in document.get('models', []) if isinstance(e, dict) and valid_model(e.get('slug'))]
    except (OSError, ValueError, TypeError): return []


# Keep the official catalog small and free of prompt/account data from the
# native models cache.  These fields are enough for Codex's model picker and
# reasoning selector, while deliberately excluding model_messages and other
# runtime-only fields.
CATALOG_FIELDS = (
    'slug', 'display_name', 'description', 'base_instructions',
    'supported_reasoning_levels', 'default_reasoning_level', 'shell_type',
    'visibility', 'supported_in_api', 'priority', 'additional_speed_tiers',
    'service_tiers', 'default_service_tier', 'support_verbosity',
    'default_verbosity', 'supports_reasoning_summaries', 'input_modalities',
    'context_window', 'max_context_window', 'effective_context_window_percent',
    'truncation_policy', 'experimental_supported_tools',
    'supports_image_detail_original', 'supports_search_tool',
    'supports_parallel_tool_calls', 'prefer_websockets', 'upgrade',
    'auto_compact_token_limit',
)


def _document(path):
    try:
        value = json.loads(pathlib.Path(path).expanduser().read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _safe_entry(value):
    if not isinstance(value, dict):
        return None
    slug = value.get('slug') or value.get('id') or value.get('model')
    if not valid_model(slug):
        return None
    entry = {key: copy.deepcopy(value[key]) for key in CATALOG_FIELDS if key in value}
    entry['slug'] = slug
    entry.setdefault('display_name', slug)
    entry.setdefault('visibility', 'list')
    entry.setdefault('supported_in_api', True)
    return entry


def _cache_entries(home):
    result = {}
    for path in (pathlib.Path(home) / 'models_cache.json',):
        document = _document(path)
        for item in document.get('models', []):
            entry = _safe_entry(item)
            if entry and entry.get('visibility', 'list') == 'list' and entry.get('supported_in_api', True):
                result[entry['slug']] = entry
    return result


def _rpc_entry(item):
    if not isinstance(item, dict):
        return None
    value = {
        'slug': item.get('id') or item.get('model'),
        'display_name': item.get('displayName'),
        'description': item.get('description'),
        'default_reasoning_level': item.get('defaultReasoningEffort'),
        'input_modalities': item.get('inputModalities'),
        'visibility': 'hide' if item.get('hidden') else 'list',
        'supported_in_api': True,
        'additional_speed_tiers': item.get('additionalSpeedTiers'),
        'service_tiers': item.get('serviceTiers'),
    }
    efforts = item.get('supportedReasoningEfforts')
    if isinstance(efforts, list):
        value['supported_reasoning_levels'] = [
            {'effort': e.get('reasoningEffort'), 'description': e.get('description', '')}
            for e in efforts if isinstance(e, dict) and valid_model(e.get('reasoningEffort'))
        ]
    return _safe_entry(value)


def refresh_official(codex_home):
    """Refresh the local official Codex model directory from app-server.

    ``model/list`` is the supported app-server discovery API.  The native
    cache is used to retain richer picker metadata and as a graceful offline
    fallback.  Existing entries are retained so an account/backend rollout
    cannot make a previously configured model disappear unexpectedly.
    """
    home = pathlib.Path(codex_home).expanduser()
    target = home / 'cc-switch-model-catalog.json'
    existing = {}
    for item in load_entries(target):
        entry = _safe_entry(item)
        if entry and entry.get('visibility', 'list') == 'list' and entry.get('supported_in_api', True):
            existing[entry['slug']] = entry
    cached = _cache_entries(home)
    discovered = {}
    source = []
    try:
        from rpc import AppServer
        with AppServer(home, overrides={'model_provider': 'openai'}, timeout=25) as app:
            result = app.call('model/list', {})
        for item in result.get('data', []):
            entry = _rpc_entry(item)
            if entry and entry.get('visibility') == 'list':
                discovered[entry['slug']] = entry
        if discovered:
            source.append('model/list')
    except Exception:
        # Offline or an older backend is still useful when its cache exists.
        pass
    merged = {}
    for entries in (existing, cached, discovered):
        for slug, entry in entries.items():
            merged[slug] = {**merged.get(slug, {}), **copy.deepcopy(entry)}
    if not merged:
        raise ValueError('Codex 模型目录为空；请先登录官方账号并重试。')
    # Stable ordering follows the backend/cache order where possible, then
    # keeps any older manually-added entries at the end.
    order = list(discovered) + [slug for slug in cached if slug not in discovered] + [
        slug for slug in existing if slug not in discovered and slug not in cached]
    entries = [merged[slug] for slug in dict.fromkeys(order)]
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps({'models': entries}, ensure_ascii=False, indent=2).encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix='.cx-model-catalog-', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'ok': True, 'path': str(target), 'count': len(entries),
            'models': [entry['slug'] for entry in entries],
            'source': '+'.join(source) if source else 'models_cache',
            'notice': '官方 Codex 模型目录已刷新；目录是可用性提示，最终权限仍以实际请求为准。'}


def generic_entry(number):
    deepseek = 'deepseek' in number.lower()
    return {'slug': number, 'display_name': number, 'description': '第三方供应商模型',
            'base_instructions': 'Help the user with coding tasks. Inspect the workspace, use available tools carefully, and verify changes.',
            'supported_reasoning_levels': [{'effort': 'low', 'description': '较少推理'}, {'effort': 'high', 'description': '较多推理'}] if deepseek else [],
            'default_reasoning_level': 'low' if deepseek else None,
            'shell_type': 'shell_command', 'visibility': 'list', 'supported_in_api': True, 'priority': 0,
            'support_verbosity': False, 'supports_reasoning_summaries': False,
            'supports_parallel_tool_calls': False, 'prefer_websockets': False,
            'input_modalities': ['text'], 'context_window': 131072,
            'effective_context_window_percent': 90,
            'truncation_policy': {'mode': 'tokens', 'limit': 10000}, 'experimental_supported_tools': [],
            **({'apply_patch_tool_type': 'freeform'} if deepseek else {})}


def build_catalog(record):
    existing = {e['slug']: e for e in load_entries(record.get('catalogPath', ''))}
    entries = []
    for number in model_ids(record.get('models'), record['model']):
        entry = copy.deepcopy(existing.get(number) or generic_entry(number))
        # The selected IDs, not a stale provider-wide source catalog, define the picker.
        entry.update({'slug': number, 'visibility': 'list', 'supported_in_api': True})
        entries.append(entry)
    return {'models': entries}


def discover(store, payload):
    record = next((p for p in store.records() if p['id'] == payload.get('id')), None)
    if record:
        url, key = record['baseUrl'], payload.get('apiKey') or read_key(store.root, record['id'])
        if payload.get('baseUrl'):
            draft = store.validate({**payload, 'model': payload.get('model') or record['model']})
            if draft['baseUrl'] != url and not payload.get('apiKey'):
                raise ValueError('修改接口地址后，请重新输入 API Key 再发现模型。')
            url = draft['baseUrl']
    else:
        record = store.validate({**payload, 'model': payload.get('model') or 'placeholder-model'})
        url, key = record['baseUrl'], payload.get('apiKey')
        if not isinstance(key, str) or not key or any(c.isspace() or ord(c) < 32 for c in key):
            raise ValueError('发现模型前请输入 API Key。')
    if not isinstance(key, str) or not key or any(c.isspace() or ord(c) < 32 for c in key):
        raise ValueError('API Key 格式无效。')
    request = urllib.request.Request(url.rstrip('/') + '/models', headers={
        'Authorization': 'Bearer ' + key, 'Accept': 'application/json', 'User-Agent': 'CX-Codex-Accounts/0.3.0'})
    try:
        environment = quota.child_environment(store.config.parent)
        proxies = {kind: environment.get(kind.upper() + '_PROXY') or environment.get(kind + '_proxy') for kind in ('http', 'https')}
        handlers = [NoRedirect()]
        if any(proxies.values()): handlers.append(urllib.request.ProxyHandler({k: v for k, v in proxies.items() if v}))
        with urllib.request.build_opener(*handlers).open(request, timeout=18) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024: raise ValueError('模型列表响应过大。')
            data = json.loads(raw)
        models = data.get('data', data.get('models', []))
        ids = sorted(set(e.get('id') or e.get('slug') for e in models if isinstance(e, dict)
                         and valid_model(e.get('id') or e.get('slug'))))
        if not ids: raise ValueError('供应商没有返回可识别的模型列表，请手动填写模型 ID。')
        return {'models': ids[:2000], 'source': 'api',
                'notice': '模型列表只证明账号能看到这些名称，不保证每个模型兼容 Responses 和 Codex 工具。'}
    except Exception as error:
        status = error.code if isinstance(error, urllib.error.HTTPError) else None
        if isinstance(error, urllib.error.HTTPError): error.close()
        fallback = [e['slug'] for e in load_entries(record.get('catalogPath', ''))] if url == record['baseUrl'] else []
        if fallback:
            return {'models': sorted(set(fallback)), 'source': 'savedCatalog',
                    'notice': '接口未返回列表，已使用原配置中的模型目录；也可手动添加模型 ID。'}
        if status:
            raise ValueError('模型列表接口返回 HTTP ' + str(status) + '；可手动填写，不能据此判定推理接口不可用。')
        if isinstance(error, ValueError): raise ValueError('模型列表无法解析，请手动填写模型 ID。')
        raise ValueError('模型发现失败，请检查网络、密钥及 /models 接口，或手动填写。')
