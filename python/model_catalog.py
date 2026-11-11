"""Public model discovery and version-compatible local Codex catalogs."""
import copy
import json
import pathlib
import re
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
