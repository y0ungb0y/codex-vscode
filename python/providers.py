"""Provider registry and reversible TOML edits; no keys leave this bridge."""
import contextlib
import copy
import datetime
import hashlib
import json
import os
import pathlib
import sys
import urllib.parse
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent / 'vendor'))
import tomlkit
from provider_key import atomic_write, check_id, encode_key, read_key
from model_catalog import build_catalog, model_ids, discover

OLD_FIELDS = ('model_provider', 'model', 'review_model', 'model_catalog_json',
          'forced_login_method', 'forced_chatgpt_workspace_id')
FIELDS = OLD_FIELDS + ('model_reasoning_effort', 'web_search', 'service_tier')


def read_bytes(path):
    return path.read_bytes() if path.exists() else None


def commit(changes, expected=None):
    """Rollback ordinary write failures; preserve edits made by another writer."""
    before = {path: read_bytes(path) for path in changes}
    if expected and any(before.get(path) != content for path, content in expected.items()):
        raise ValueError('配置已被其他程序修改，请刷新后重试。')
    applied = []
    try:
        for path, content in changes.items():
            if read_bytes(path) != before[path]:
                raise ValueError('配置已被其他程序修改，请刷新后重试。')
            if content is None:
                if path.exists():
                    if path.is_symlink():
                        raise ValueError('供应商文件不应是符号链接。')
                    path.unlink()
            else:
                atomic_write(path, content)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            if read_bytes(path) == changes[path]:
                if before[path] is None:
                    if path.exists(): path.unlink()
                else:
                    atomic_write(path, before[path])
        raise


class Providers:
    def __init__(self, accounts_root, codex_home):
        self.root = pathlib.Path(accounts_root) / 'providers'
        self.config = pathlib.Path(codex_home) / 'config.toml'
        self.registry = self.root / 'registry.json'
        home_id = hashlib.sha256(str(self.config.parent.resolve()).encode()).hexdigest()[:24]
        self.state_path = self.root / ('state-' + home_id + '.json')

    def load(self, path, default):
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        except (ValueError, OSError):
            raise ValueError('供应商记录无法读取，请检查 CX 供应商目录。')

    def document(self):
        if self.config.is_symlink():
            raise ValueError('config.toml 是符号链接，请先改用独立文件。')
        raw = read_bytes(self.config)
        try:
            return raw, tomlkit.parse((raw or b'').decode('utf-8-sig'))
        except Exception:
            raise ValueError('config.toml 格式无效；未修改配置，请先修复。')

    def records(self):
        return self.load(self.registry, {'providers': []})['providers']

    def secret_path(self, number):
        return self.root / 'secrets' / (check_id(number) + '.json')

    def fingerprint(self, doc, fields=FIELDS):
        values = {k: doc[k].unwrap() if hasattr(doc[k], 'unwrap') else doc[k]
                  for k in fields if k in doc}
        table = doc.get('model_providers', {}).get(str(doc.get('model_provider', 'openai')))
        if table is not None:
            values['providerDefinition'] = table.unwrap() if hasattr(table, 'unwrap') else table
        return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()

    def matches(self, doc, state):
        fields = FIELDS if state.get('schema', 2) >= 3 else OLD_FIELDS
        return self.fingerprint(doc, fields) == state['applied']

    def snapshot(self):
        _, doc = self.document()
        active = str(doc.get('model_provider', 'openai'))
        records = self.records()
        managed = next((p for p in records if 'cx_' + p['id'] == active or p.get('sourceId') == active), None)
        return {'mode': 'official' if active == 'openai' else 'thirdParty',
                'providerId': active,
                'activeId': managed['id'] if managed else None,
                'activeName': managed['name'] if managed else str(doc.get('model_providers', {}).get(active, {}).get('name', active)),
                'model': str(doc.get('model', '默认模型')),
                'canRestore': self.state_path.exists(),
                'storage': 'Windows 用户加密' if os.name == 'nt' else '仅当前用户可读的文件（0600）',
                'providers': [{**p, 'hasKey': self.secret_path(p['id']).exists(),
                               'selected': managed is not None and p['id'] == managed['id']}
                              for p in records]}

    def validate(self, payload):
        if not isinstance(payload, dict): raise ValueError('供应商表单无效。')
        result = {}
        for key, label, limit in [('name', '名称', 80), ('baseUrl', '接口地址', 2048), ('model', '模型', 160)]:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError(label + '不能为空，且长度和格式必须有效。')
            result[key] = value.strip()
        url = urllib.parse.urlsplit(result['baseUrl'])
        if (url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c.isspace() for c in result['baseUrl'])):
            raise ValueError('接口地址必须是 HTTP(S) URL，不能包含账号、密码、查询参数或片段。')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('非本机供应商请使用 HTTPS，避免明文传输密钥。')
        result['baseUrl'] = result['baseUrl'].rstrip('/')
        if re_invalid_model(result['model']):
            raise ValueError('模型名称不能包含空白字符。')
        result['models'] = model_ids(payload.get('models'), result['model'])
        return result

    def encode(self, value):
        return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')

    def save(self, payload):
        record = self.validate(payload)
        records = self.records()
        number = payload.get('id')
        old = next((p for p in records if p['id'] == number), None)
        if number and old is None: raise ValueError('供应商已不存在，请刷新。')
        record['id'] = check_id(number) if number else uuid.uuid4().hex
        if old and 'models' not in payload:
            record['models'] = model_ids(old.get('models'), record['model'])
        if old:
            for key in ('sourceId', 'catalogPath'):
                if key in old: record[key] = old[key]
        key = payload.get('apiKey', '')
        if not isinstance(key, str): raise ValueError('API Key 格式无效。')
        if not key and not self.secret_path(record['id']).exists():
            raise ValueError('首次添加供应商时请输入 API Key。')
        changes = {}
        if key: changes[self.secret_path(record['id'])] = encode_key(key)
        updated = [record if p['id'] == number else p for p in records] if old else records + [record]
        changes[self.registry] = self.encode({'providers': updated})
        active = self.snapshot()['activeId'] == record['id']
        if active:
            changes.update(self.activation_changes(record))
        commit(changes, {self.config: self.expected_config} if active else None)
        return {**self.snapshot(), 'requiresReload': active, 'savedId': record['id']}

    def import_current(self):
        """Import an already-working custom provider without editing config/auth."""
        raw, doc = self.document()
        active = str(doc.get('model_provider', 'openai'))
        records = self.records()
        existing = next((p for p in records if 'cx_' + p['id'] == active or p.get('sourceId') == active), None)
        if existing and 'cx_' + existing['id'] == active:
            return {**self.snapshot(), 'savedId': existing['id'], 'alreadyImported': True}
        table = doc.get('model_providers', {}).get(active)
        if active == 'openai' or not isinstance(table, dict) and not hasattr(table, 'get'):
            raise ValueError('当前没有可导入的自定义供应商，请使用“添加第三方供应商”。')
        if table.get('wire_api', 'responses') != 'responses':
            raise ValueError('当前配置不是 Responses 协议，不能直接导入。')
        if any(table.get(field) for field in ('http_headers', 'env_http_headers', 'query_params', 'gateway_oauth', 'auth')):
            raise ValueError('此配置使用自定义认证或请求参数，请保留原配置；本版导入仅支持标准 Bearer API Key。')
        key = table.get('experimental_bearer_token')
        if not key and table.get('env_key'):
            key = os.environ.get(str(table['env_key']))
        if not key:
            raise ValueError('无法从当前配置读取 API Key，请使用表单手动添加。')
        record = self.validate({'name': str(table.get('name') or active), 'baseUrl': str(table.get('base_url') or ''),
                                'model': str(doc.get('model') or '')})
        record.update({'id': existing['id'] if existing else uuid.uuid4().hex, 'sourceId': active})
        if doc.get('model_catalog_json'):
            record['catalogPath'] = str(doc['model_catalog_json'])
        updated = [record if p['id'] == existing['id'] else p for p in records] if existing else records + [record]
        changes = {self.registry: self.encode({'providers': updated}),
                   self.secret_path(record['id']): encode_key(str(key))}
        changes[self.state_path] = self.encode({'original': (raw or b'').decode('utf-8-sig'), 'schema': 3,
                                                'hadFile': raw is not None, 'applied': self.fingerprint(doc)})
        # The source config may be concurrently rewritten by CC Switch.
        if read_bytes(self.config) != raw:
            raise ValueError('配置已被其他程序修改，请刷新后重试。')
        commit(changes)
        return {**self.snapshot(), 'savedId': record['id'], 'requiresReload': False}

    def backup_changes(self, raw):
        if raw is None: return {}
        name = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.toml'
        return {self.root / 'config-backups' / name: raw}

    def activation_changes(self, record):
        raw, doc = self.document()
        self.expected_config = raw
        state = self.load(self.state_path, None)
        if state and not self.matches(doc, state):
            raise ValueError('接入配置已被外部修改。请先使用“恢复接入前配置”，再切换。')
        if not state: state = {'original': (raw or b'').decode('utf-8-sig'), 'hadFile': raw is not None}
        if state.get('schema', 2) < 3:
            original = tomlkit.parse(state['original'])
            for key in FIELDS:
                if key not in OLD_FIELDS:
                    if key in original: del original[key]
                    if key in doc: original[key] = copy.deepcopy(doc[key])
            state['original'] = tomlkit.dumps(original)
        catalog = build_catalog(record)
        default_entry = next(e for e in catalog['models'] if e['slug'] == record['model'])
        old_effort = doc.get('model_reasoning_effort')
        old_tier = doc.get('service_tier')
        for field in FIELDS:
            if field in doc: del doc[field]
        doc['model_provider'] = 'cx_' + record['id']
        doc['model'] = record['model']
        catalog_path = self.root / 'catalogs' / (record['id'] + '.json')
        doc['model_catalog_json'] = str(catalog_path.resolve())
        efforts = [e.get('effort') for e in default_entry.get('supported_reasoning_levels', [])]
        if efforts:
            doc['model_reasoning_effort'] = old_effort if old_effort in efforts else default_entry.get('default_reasoning_level') or efforts[0]
        doc['web_search'] = 'disabled'
        if record['model'].lower().startswith(('gpt-', 'o1', 'o3', 'o4')) and old_tier:
            doc['service_tier'] = old_tier
        table = tomlkit.table()
        table.update({'name': record['name'], 'base_url': record['baseUrl'], 'wire_api': 'responses'})
        table['auth'] = {'command': sys.executable,
                         'args': [str((self.root / 'credential_helper.py').resolve()),
                                  str(self.root.resolve()), record['id']],
                         'timeout_ms': 5000, 'refresh_interval_ms': 0}
        if 'model_providers' not in doc: doc['model_providers'] = tomlkit.table()
        doc['model_providers']['cx_' + record['id']] = table
        state['schema'] = 3
        state['applied'] = self.fingerprint(doc)
        changes = self.backup_changes(raw)
        changes[self.root / 'credential_helper.py'] = (pathlib.Path(__file__).parent / 'provider_key.py').read_bytes()
        changes[self.config] = tomlkit.dumps(doc).encode('utf-8')
        changes[catalog_path] = self.encode(catalog)
        changes[self.state_path] = self.encode(state)
        return changes

    def activate(self, number):
        check_id(number)
        record = next((p for p in self.records() if p['id'] == number), None)
        if record is None: raise ValueError('供应商已不存在，请刷新。')
        try: read_key(self.root, number)
        except Exception: raise ValueError('密钥无法读取，请编辑供应商并重新输入 API Key。')
        changes = self.activation_changes(record)
        commit(changes, {self.config: self.expected_config})
        return {**self.snapshot(), 'requiresReload': True}

    def restore(self, official=False, force=False):
        raw, doc = self.document()
        state = self.load(self.state_path, None)
        if state and not force and not self.matches(doc, state):
            raise ValueError('接入配置已被外部修改。请先使用“恢复接入前配置”，再切换。')
        if not state:
            if official and str(doc.get('model_provider', 'openai')) != 'openai':
                raise ValueError('当前为 CX 以外的供应商配置；请先手动恢复官方配置再选择账号。')
            if official and doc.get('forced_login_method') == 'api':
                doc['forced_login_method'] = 'chatgpt'
                changes = self.backup_changes(raw)
                changes[self.config] = tomlkit.dumps(doc).encode('utf-8')
                commit(changes, {self.config: raw})
            return self.snapshot()
        original = tomlkit.parse(state['original'])
        for field in FIELDS if state.get('schema', 2) >= 3 else OLD_FIELDS:
            if field in doc: del doc[field]
            if field in original: doc[field] = copy.deepcopy(original[field])
        # Explicit ChatGPT selection always returns to the official provider.
        if official and str(doc.get('model_provider', 'openai')) != 'openai':
            for field in ('model_provider', 'model', 'review_model', 'model_catalog_json'):
                if field in doc: del doc[field]
        if official and doc.get('forced_login_method') == 'api':
            doc['forced_login_method'] = 'chatgpt'
        owned = {'cx_' + p['id'] for p in self.records()}
        if 'model_providers' in doc:
            for name in list(doc['model_providers']):
                if name in owned and name not in original.get('model_providers', {}):
                    del doc['model_providers'][name]
            if not doc['model_providers'] and 'model_providers' not in original:
                del doc['model_providers']
        changes = self.backup_changes(raw)
        changes[self.config] = tomlkit.dumps(doc).encode('utf-8')
        changes[self.state_path] = None
        commit(changes, {self.config: raw})
        return {**self.snapshot(), 'requiresReload': True}

    def delete(self, number):
        check_id(number)
        if self.snapshot()['activeId'] == number:
            raise ValueError('请先切换到其他供应商或 ChatGPT 账号，再删除当前供应商。')
        records = self.records()
        if not any(p['id'] == number for p in records): raise ValueError('供应商已不存在，请刷新。')
        changes = {self.registry: self.encode({'providers': [p for p in records if p['id'] != number]}),
                   self.secret_path(number): None}
        raw, doc = self.document()
        name = 'cx_' + number
        if name in doc.get('model_providers', {}):
            del doc['model_providers'][name]
            changes.update(self.backup_changes(raw))
            changes[self.config] = tomlkit.dumps(doc).encode('utf-8')
        commit(changes, {self.config: raw} if self.config in changes else None)
        return self.snapshot()

    @contextlib.contextmanager
    def account_mode(self):
        files = [self.config, self.state_path]
        before = {p: read_bytes(p) for p in files}
        self.restore(official=True)
        applied = {p: read_bytes(p) for p in files}
        try:
            yield
        except Exception:
            commit(before, applied)
            raise


def re_invalid_model(value):
    return any(c.isspace() for c in value)
