"""Real installed Codex -> isolated fixture config -> local Responses server.

No production credentials or paid provider are used. Run explicitly, not as a
unit test; only a pass/fail summary is printed.
"""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from providers import Providers
from quota_status import backend_command
from rpc import AppServer
import history

seen = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        size = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(size))
        seen.append({'path': self.path, 'authorized': self.headers.get('Authorization') == 'Bearer cx-fixture-only',
                     'model': body.get('model')})
        message = {'id': 'msg_fixture', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                   'content': [{'type': 'output_text', 'text': 'CX_MOCK_OK', 'annotations': []}]}
        response = {'id': 'resp_fixture', 'object': 'response', 'created_at': 1794360000, 'status': 'completed',
                    'model': 'cx-fixture-model', 'output': [message],
                    'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2,
                              'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}
        events = [
            ('response.created', {'response': {**response, 'status': 'in_progress', 'output': []}}),
            ('response.output_item.added', {'output_index': 0, 'item': {**message, 'status': 'in_progress', 'content': []}}),
            ('response.content_part.added', {'item_id': message['id'], 'output_index': 0, 'content_index': 0,
                                            'part': {'type': 'output_text', 'text': '', 'annotations': []}}),
            ('response.output_text.delta', {'item_id': message['id'], 'output_index': 0, 'content_index': 0, 'delta': 'CX_MOCK_OK'}),
            ('response.output_text.done', {'item_id': message['id'], 'output_index': 0, 'content_index': 0, 'text': 'CX_MOCK_OK'}),
            ('response.output_item.done', {'output_index': 0, 'item': message}),
            ('response.completed', {'response': response}),
        ]
        stream = ''.join('event: ' + kind + '\ndata: ' + json.dumps({'type': kind, **data}) + '\n\n' for kind, data in events).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(stream)))
        self.end_headers()
        self.wfile.write(stream)


def main():
    with tempfile.TemporaryDirectory(prefix='cx-provider-smoke-') as temporary:
        root = pathlib.Path(temporary)
        home = root / 'codex'
        home.mkdir()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        store = Providers(root / 'accounts', home)
        saved = store.save({'name': 'CX local fixture', 'baseUrl': 'http://127.0.0.1:' + str(server.server_port) + '/v1',
                            'model': 'cx-fixture-model', 'apiKey': 'cx-fixture-only'})
        store.activate(saved['savedId'])
        with AppServer(home) as app:
            listed = app.call('model/list', {'includeHidden': True}).get('data', [])
            assert any(m.get('model') == 'cx-fixture-model' or m.get('id') == 'cx-fixture-model' for m in listed), 'Custom model is missing from Codex model/list'
        env = os.environ.copy()
        env['CODEX_HOME'] = str(home)
        env['NO_PROXY'] = env['no_proxy'] = '127.0.0.1,localhost'
        for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
            env.pop(key, None)
        command = backend_command() + ['-c', 'features.plugins=false', '-c', 'features.remote_plugin=false',
                    '-c', 'features.apps=false', '-c', 'features.daemon_auto_start=false',
                    '-c', 'features.api_key_model_discovery=false', '-c', 'analytics.enabled=false',
                    'exec', '--skip-git-repo-check', '--json', '-C', str(root),
                    '--sandbox', 'read-only', 'Reply CX_MOCK_OK. Do not use tools.']
        try:
            result = subprocess.run(command, env=env, cwd=str(root), capture_output=True, timeout=45)
        finally:
            server.shutdown()
        if result.returncode != 0:
            # All data in this isolated process is synthetic. Exclude headers and
            # tokens anyway; retain config error lines for diagnosing compatibility.
            for line in result.stderr.decode('utf-8', errors='replace').splitlines():
                if any(word in line.lower() for word in ('error loading', 'unknown field', 'invalid value', 'error:')):
                    print(line.replace('cx-fixture-only', '[fixture]')[:300])
            raise AssertionError('Isolated Codex process did not complete; exit ' + str(result.returncode))
        assert seen and seen[-1]['authorized'], 'Codex did not use the configured credential helper'
        assert seen[-1]['path'].split('?')[0] == '/v1/responses'
        assert seen[-1]['model'] == 'cx-fixture-model'
        assert b'CX_MOCK_OK' in result.stdout
        original = history.list_threads(home, {})['threads'][0]
        second = store.save({'name': 'Second fixture', 'baseUrl': 'http://127.0.0.1:' + str(server.server_port) + '/v1',
                            'model': 'cx-fixture-model', 'apiKey': 'cx-fixture-only'})
        store.activate(second['savedId'])
        forked = history.fork_thread(home, {'id': original['id']})
        assert forked['modelProvider'] == 'cx_' + second['savedId']
        all_threads = history.list_threads(home, {})['threads']
        assert any(t['id'] == original['id'] and t['modelProvider'] == original['modelProvider'] for t in all_threads)
        # Some backends list a new fork only after its first new user turn.
        fork_read = history.read_thread(home, {'id': forked['id']})
        assert fork_read['messages'], 'Native fork did not preserve visible messages'
        print('PASS: native model/list, credential helper, Responses reply, all-provider history and cross-provider fork')


if __name__ == '__main__': main()
