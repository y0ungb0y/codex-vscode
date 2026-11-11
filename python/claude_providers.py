"""Claude Code Anthropic-compatible providers, isolated from Codex configuration."""
import copy
import contextlib
import datetime
import hashlib
import json
import os
import pathlib
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid

from providers import Providers, commit, read_bytes
from provider_key import check_id, encode_key, read_key

MODEL_FIELDS = {
    'haikuModel': 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
    'sonnetModel': 'ANTHROPIC_DEFAULT_SONNET_MODEL',
    'opusModel': 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'fableModel': 'ANTHROPIC_DEFAULT_FABLE_MODEL',
    'subagentModel': 'CLAUDE_CODE_SUBAGENT_MODEL',
}
ENV_FIELDS = ('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY',
              'ANTHROPIC_MODEL', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK',
              'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY') + tuple(MODEL_FIELDS.values()) + (
                  'ANTHROPIC_DEFAULT_SONNET_MODEL_NAME', 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME')
TOP_FIELDS = ('model', 'apiKeyHelper')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ClaudeProviders(Providers):
    def __init__(self, accounts_root, claude_home, cc_switch_home=None):
        super().__init__(pathlib.Path(accounts_root) / 'claude', claude_home)
        self.config = pathlib.Path(claude_home) / 'settings.json'
        self.cc_home = pathlib.Path(cc_switch_home or pathlib.Path.home() / '.cc-switch')

    def document(self):
        if self.config.is_symlink():
            raise ValueError('Claude settings.json 是符号链接，请改用独立文件。')
        raw = read_bytes(self.config)
        try:
            doc = json.loads((raw or b'{}').decode('utf-8-sig'))
            if not isinstance(doc, dict) or not isinstance(doc.get('env', {}), dict):
                raise ValueError()
            return raw, doc
        except (ValueError, UnicodeError):
            raise ValueError('Claude settings.json 格式无效；未修改配置。')

    def fingerprint(self, doc, fields=None):
        values = {'env': {k: v for k, v in doc.get('env', {}).items() if k in ENV_FIELDS},
                  'top': {k: doc[k] for k in TOP_FIELDS if k in doc}}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def matches(self, doc, state):
        return self.fingerprint(doc) == state.get('applied')

    def validate(self, payload):
        record = super().validate(payload)
        auth = payload.get('authType', 'token')
        if auth not in ('token', 'apiKey'):
            raise ValueError('认证方式必须是 Bearer Token 或 x-api-key。')
        record['authType'] = auth
        for key in MODEL_FIELDS:
            value = payload.get(key, '')
            if not isinstance(value, str) or len(value) > 160 or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError('模型映射格式无效。')
            record[key] = value
        # A provider may intentionally customize the display names for aliases.
        record['modelNames'] = {k: v for k, v in payload.get('modelNames', {}).items()
                                if k in ENV_FIELDS and k.endswith('_NAME') and isinstance(v, str)}
        return record

    def snapshot(self):
        _, doc = self.document()
        env = doc.get('env', {})
        state = self.load(self.state_path, None)
        records = self.records()
        active = next((p for p in records if state and self.matches(doc, state)
                       and p['id'] == state.get('activeId')), None)
        if active:
            key_field = 'ANTHROPIC_API_KEY' if active.get('authType') == 'apiKey' else 'ANTHROPIC_AUTH_TOKEN'
            try:
                if (env.get(key_field) != read_key(self.root, active['id'])
                        or active['baseUrl'] != env.get('ANTHROPIC_BASE_URL')
                        or active['model'] != (env.get('ANTHROPIC_MODEL') or doc.get('model') or 'sonnet')):
                    active = None
            except (ValueError, OSError):
                active = None
        third_party = bool(env.get('ANTHROPIC_BASE_URL'))
        return {'mode': 'thirdParty' if third_party else 'unconfigured',
                'activeId': active['id'] if active else None,
                'activeName': active['name'] if active else '当前 Claude 配置',
                'model': str(env.get('ANTHROPIC_MODEL') or doc.get('model') or '默认模型'),
                'canRestore': state is not None, 'application': 'claude',
                'storage': 'Windows 用户加密；启用时写入 Claude 用户 settings.json' if os.name == 'nt'
                           else '仅当前用户可读；启用时写入 Claude 用户 settings.json',
                'providers': [{**p, 'hasKey': self.secret_path(p['id']).exists(),
                               'selected': active is not None and p['id'] == active['id']} for p in records]}

    def save(self, payload):
        # An active provider edited with a new key must apply the new key atomically.
        self.pending_key = payload.get('apiKey')
        try:
            return super().save(payload)
        finally:
            self.pending_key = None

    def backup_changes(self, raw):
        if raw is None:
            return {}
        name = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.json'
        return {self.root / 'config-backups' / name: raw}

    def activation_changes(self, record):
        raw, doc = self.document()
        self.expected_config = raw
        state = self.load(self.state_path, None)
        if state and not self.matches(doc, state):
            raise ValueError('Claude 接入配置已被外部修改，请先导入当前配置或恢复接入前配置。')
        if not state:
            state = {'original': doc, 'hadFile': raw is not None}
        doc = copy.deepcopy(doc)
        env = doc.setdefault('env', {})
        for field in ENV_FIELDS:
            env.pop(field, None)
        for field in TOP_FIELDS:
            doc.pop(field, None)
        env['ANTHROPIC_BASE_URL'] = record['baseUrl']
        env['ANTHROPIC_MODEL'] = record['model']
        doc['model'] = record['model']
        key_field = 'ANTHROPIC_API_KEY' if record['authType'] == 'apiKey' else 'ANTHROPIC_AUTH_TOKEN'
        env[key_field] = getattr(self, 'pending_key', None) or read_key(self.root, record['id'])
        for field, variable in MODEL_FIELDS.items():
            # Unmapped tiers use the provider's default, never an unrelated provider's model.
            env[variable] = record.get(field) or record['model']
        env.update(record.get('modelNames', {}))
        state = {**state, 'activeId': record['id'], 'applied': self.fingerprint(doc)}
        return {**self.backup_changes(raw), self.config: self.encode(doc), self.state_path: self.encode(state)}

    def restore(self, official=False, force=False):
        raw, doc = self.document()
        state = self.load(self.state_path, None)
        if not state:
            return self.snapshot()
        if not force and not self.matches(doc, state):
            raise ValueError('Claude 接入配置已被外部修改，请先刷新。')
        original = state['original']
        env = doc.setdefault('env', {})
        for field in ENV_FIELDS:
            env.pop(field, None)
            if field in original.get('env', {}):
                env[field] = original['env'][field]
        for field in TOP_FIELDS:
            doc.pop(field, None)
            if field in original:
                doc[field] = original[field]
        if not env and 'env' not in original:
            doc.pop('env', None)
        content = self.encode(doc) if doc or state['hadFile'] else None
        commit({**self.backup_changes(raw), self.config: content, self.state_path: None}, {self.config: raw})
        return {**self.snapshot(), 'requiresReload': True}

    def delete(self, number):
        check_id(number)
        if self.snapshot()['activeId'] == number:
            raise ValueError('请先切换供应商或恢复接入前配置，再删除当前供应商。')
        records = self.records()
        if not any(p['id'] == number for p in records):
            raise ValueError('供应商已不存在，请刷新。')
        commit({self.registry: self.encode({'providers': [p for p in records if p['id'] != number]}),
                self.secret_path(number): None})
        return self.snapshot()

    def import_document(self, name, doc, source=None):
        env = doc.get('env', {})
        auth_type = 'token' if env.get('ANTHROPIC_AUTH_TOKEN') else 'apiKey'
        key = env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')
        if not key or not env.get('ANTHROPIC_BASE_URL'):
            raise ValueError('此配置没有可导入的第三方地址和密钥。')
        payload = {'name': name, 'baseUrl': env['ANTHROPIC_BASE_URL'],
                   'model': env.get('ANTHROPIC_MODEL') or doc.get('model') or env.get('ANTHROPIC_DEFAULT_SONNET_MODEL') or 'sonnet',
                   'authType': auth_type, **{f: env.get(v, '') for f, v in MODEL_FIELDS.items()},
                   'modelNames': {k: v for k, v in env.items() if k in ENV_FIELDS and k.endswith('_NAME')}}
        record = self.validate(payload)
        records = self.records()
        existing = next((p for p in records if source and p.get('sourceId') == source), None)
        if not existing:
            existing = next((p for p in records if p['baseUrl'] == record['baseUrl'] and p['model'] == record['model']), None)
        record['id'] = existing['id'] if existing else uuid.uuid4().hex
        if source:
            record['sourceId'] = source
        updated = [record if p['id'] == record['id'] else p for p in records] if existing else records + [record]
        return record, {self.registry: self.encode({'providers': updated}), self.secret_path(record['id']): encode_key(key)}

    def import_current(self):
        raw, doc = self.document()
        # Existing snapshot uses real settings, while all keys stay inside Python.
        env = doc.get('env', {})
        existing = next((p for p in self.records() if p['baseUrl'] == env.get('ANTHROPIC_BASE_URL')
                         and p['model'] == (env.get('ANTHROPIC_MODEL') or doc.get('model') or 'sonnet')), None)
        record, changes = self.import_document(existing['name'] if existing else '当前 Claude 供应商', doc)
        state = self.load(self.state_path, None)
        if not state:
            state = {'original': doc, 'hadFile': raw is not None}
        changes[self.state_path] = self.encode({**state, 'activeId': record['id'], 'applied': self.fingerprint(doc)})
        if read_bytes(self.config) != raw:
            raise ValueError('Claude 配置已被其他程序修改，请刷新后重试。')
        commit(changes)
        return {**self.snapshot(), 'savedId': record['id'], 'requiresReload': False}

    def import_cc_switch(self):
        db = self.cc_home / 'cc-switch.db'
        if not db.is_file():
            raise ValueError('未找到 CC Switch 数据库，请先导入当前 Claude 配置或手动添加。')
        try:
            with contextlib.closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
                rows = connection.execute("SELECT id, name, settings_config FROM providers WHERE app_type = 'claude'").fetchall()
        except sqlite3.Error:
            raise ValueError('CC Switch 数据库暂时无法读取；请退出其配置编辑后重试。')
        imported, skipped = 0, 0
        before_registry = read_bytes(self.registry)
        before_secrets = {p: read_bytes(p) for p in (self.root / 'secrets').glob('*.json')}
        try:
            for source, name, settings in rows:
                doc = json.loads(settings)
                env = doc.get('env', {})
                if not env.get('ANTHROPIC_BASE_URL') or not (env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')):
                    skipped += 1
                    continue
                _, changes = self.import_document(name, doc, 'cc-switch:' + source)
                commit(changes)
                imported += 1
        except Exception:
            changes = {self.registry: before_registry, **before_secrets}
            changes.update({p: None for p in (self.root / 'secrets').glob('*.json') if p not in before_secrets})
            commit(changes)
            raise ValueError('CC Switch 导入失败；原 CX 供应商记录已保留。')
        return {**self.snapshot(), 'imported': imported, 'skipped': skipped}

    def test_connection(self, payload):
        record = next((p for p in self.records() if p['id'] == payload.get('id')), None)
        if not record:
            raise ValueError('请先保存供应商，再测试连接。')
        key = read_key(self.root, record['id'])
        base = record['baseUrl'].rstrip('/')
        url = base + ('/messages' if base.endswith('/v1') else '/v1/messages')
        headers = {'Content-Type': 'application/json', 'anthropic-version': '2023-06-01',
                   'User-Agent': 'CX-Claude-Provider-Test/0.4.0'}
        headers['x-api-key' if record['authType'] == 'apiKey' else 'Authorization'] = key if record['authType'] == 'apiKey' else 'Bearer ' + key
        request = urllib.request.Request(url, data=json.dumps({'model': record['model'], 'max_tokens': 32,
            'messages': [{'role': 'user', 'content': 'Reply with OK only.'}]}).encode(), headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
                data = json.loads(response.read(1024 * 1024))
            if data.get('type') != 'message' or not isinstance(data.get('content'), list) or not data['content']:
                raise ValueError()
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise ValueError('Claude 连接测试返回 HTTP ' + str(code) + '；请检查密钥、模型及 Anthropic Messages 接口。')
        except Exception:
            raise ValueError('Claude 连接测试失败；请检查网络及 Anthropic Messages 接口。')
        return {'ok': True, 'model': record['model'], 'message': 'Anthropic Messages 最小请求成功；未读取或发送工作区文件。'}

    def models(self, payload):
        record = next((p for p in self.records() if p['id'] == payload.get('id')), None) or self.validate(payload)
        models = list(dict.fromkeys([record['model']] + record.get('models', []) + [record[f] for f in MODEL_FIELDS if record.get(f)]))
        return {'models': models, 'notice': 'Claude 使用默认模型与分档映射；可在表单手动填写模型 ID。'}
