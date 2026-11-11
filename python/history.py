"""Unified local history using native APIs, never rewrites session databases."""
import re
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / 'vendor'))
import tomlkit

from rpc import AppServer, RpcError


def thread_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
        raise ValueError('会话编号无效。')
    return value


def list_threads(home, payload):
    params = {'limit': 50, 'sortKey': 'updated_at', 'modelProviders': [],
              'sourceKinds': ['cli', 'vscode', 'exec', 'appServer', 'unknown'],
              'useStateDbOnly': True, 'archived': bool(payload.get('archived'))}
    if payload.get('cursor'): params['cursor'] = str(payload['cursor'])[:1024]
    if payload.get('search'): params['searchTerm'] = str(payload['search'])[:200]
    with AppServer(home) as server: result = server.call('thread/list', params)
    summaries = []
    for item in result.get('data', []):
        summary = {k: item.get(k) for k in ('id', 'modelProvider', 'createdAt', 'updatedAt')}
        for key, limit in (('name', 160), ('preview', 600), ('cwd', 4096)):
            summary[key] = str(item[key])[:limit] if item.get(key) is not None else None
        summary['status'] = {'type': (item.get('status') or {}).get('type')}
        summaries.append(summary)
    return {'threads': summaries, 'nextCursor': result.get('nextCursor')}


def read_thread(home, payload):
    number = thread_id(payload.get('id'))
    with AppServer(home) as server:
        thread = server.call('thread/read', {'threadId': number, 'includeTurns': False}).get('thread', {})
        try:
            result = server.call('thread/turns/list', {'threadId': number, 'limit': 30,
                                 'sortDirection': 'desc', 'itemsView': 'full', **({'cursor': payload['cursor']} if payload.get('cursor') else {})})
            turns = list(reversed(result.get('data', [])))
            cursor = result.get('nextCursor')
        except RpcError as error:
            if error.code != -32601: raise
            turns = server.call('thread/read', {'threadId': number, 'includeTurns': True}).get('thread', {}).get('turns', [])
            cursor = None
    messages = []
    for turn in turns:
        for item in turn.get('items', []):
            kind = item.get('type')
            if kind == 'userMessage':
                text = '\n'.join(part.get('text', '') for part in item.get('content', []) if part.get('type') == 'text')
                if text: messages.append({'role': '用户', 'text': text[:100000]})
            elif kind == 'agentMessage' and item.get('text'):
                messages.append({'role': '助手', 'text': str(item['text'])[:100000]})
            elif kind in ('commandExecution', 'fileChange', 'mcpToolCall', 'dynamicToolCall'):
                messages.append({'role': '工具', 'text': str(item.get('command') or item.get('tool') or kind)[:2000]})
    budget, bounded = 700000, []
    for message in reversed(messages):
        message['text'] = message['text'][-50000:]
        size = len(json.dumps(message, ensure_ascii=True))
        if size > budget: break
        budget -= size
        bounded.append(message)
    return {'id': number, 'name': (thread.get('name') or thread.get('preview') or number)[:200],
            'modelProvider': thread.get('modelProvider'), 'messages': list(reversed(bounded)),
            'truncated': len(bounded) != len(messages), 'nextCursor': cursor}


def fork_thread(home, payload):
    number = thread_id(payload.get('id'))
    try:
        config = tomlkit.parse((pathlib.Path(home) / 'config.toml').read_text(encoding='utf-8-sig'))
    except FileNotFoundError: config = {}
    except Exception: raise ValueError('当前 Codex 配置无法读取，请先修复配置。')
    params = {'threadId': number, 'excludeTurns': True, 'modelProvider': str(config.get('model_provider', 'openai'))}
    if config.get('model'): params['model'] = str(config['model'])
    with AppServer(home) as server:
        # Native fork preserves the original thread and handles encrypted storage.
        result = server.call('thread/fork', params)
    thread = result.get('thread') or {}
    if not thread.get('id'): raise ValueError('未能创建会话分支，原记录保持不变。')
    return {'id': thread['id'], 'modelProvider': thread.get('modelProvider'), 'forkedFromId': number}
