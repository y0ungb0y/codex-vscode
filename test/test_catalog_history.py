import http.server
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from providers import Providers
import model_catalog
import history


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temp.name)
        self.store = Providers(self.base / 'accounts', self.base / 'codex')

    def tearDown(self): self.temp.cleanup()

    def test_arbitrary_model_ids_appear_in_catalog_and_deepseek_has_safe_defaults(self):
        saved = self.store.save({'name': 'Gateway', 'baseUrl': 'https://example.invalid/v1',
          'model': 'deepseek-v4.1-flash-1017', 'models': ['qwen3-test', 'glm-test'], 'apiKey': 'fixture'})
        self.store.activate(saved['savedId'])
        _, doc = self.store.document()
        catalog = json.loads(pathlib.Path(doc['model_catalog_json']).read_text(encoding='utf-8'))
        self.assertEqual([e['slug'] for e in catalog['models']], ['deepseek-v4.1-flash-1017', 'qwen3-test', 'glm-test'])
        self.assertEqual(doc['model_reasoning_effort'], 'low')
        self.assertEqual(doc['web_search'], 'disabled')
        self.assertNotIn('service_tier', doc)
        self.assertFalse(catalog['models'][0]['prefer_websockets'])

    def test_discovery_accepts_openai_ids_and_codex_slugs_without_returning_key(self):
        seen = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                body = json.dumps({'data': [{'id': 'deepseek-test'}, {'slug': 'qwen-test'}, {'id': 'bad name'}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = model_catalog.discover(self.store, {'name': 'Fixture', 'baseUrl': 'http://127.0.0.1:' + str(server.server_port), 'apiKey': 'fixture-secret'})
            self.assertEqual(result['models'], ['deepseek-test', 'qwen-test'])
            self.assertNotIn('fixture-secret', json.dumps(result))
            self.assertEqual(seen, ['Bearer fixture-secret'])
        finally: server.shutdown(); server.server_close()

    def test_discovery_refuses_redirects_and_does_not_leak_key_in_errors(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(302); self.send_header('Location', 'https://do-not-follow.invalid/models'); self.end_headers()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(ValueError) as error:
                model_catalog.discover(self.store, {'name': 'Fixture', 'baseUrl': 'http://127.0.0.1:' + str(server.server_port), 'apiKey': 'fixture-secret'})
            self.assertIn('302', str(error.exception))
            self.assertNotIn('fixture-secret', str(error.exception))
        finally: server.shutdown(); server.server_close()

    def test_catalog_uses_only_selected_source_entries_preserving_known_metadata(self):
        source = self.base / 'catalog.json'
        source.write_text(json.dumps({'models': [{'slug': 'known-model', 'context_window': 333000}, {'slug': 'stale-model'}]}))
        catalog = model_catalog.build_catalog({'model': 'known-model', 'models': ['deepseek-test'], 'catalogPath': str(source)})
        self.assertEqual(len(catalog['models']), 2)
        self.assertEqual(catalog['models'][0]['context_window'], 333000)
        self.assertNotIn('stale-model', json.dumps(catalog))


class HistoryTests(unittest.TestCase):
    def server(self, handler):
        class FakeServer:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def call(self, method, params): return handler(method, params)
        return mock.patch.object(history, 'AppServer', FakeServer)

    def test_history_requests_all_providers_without_resuming_or_rewriting_threads(self):
        calls = []
        def handler(method, params):
            calls.append((method, params))
            return {'data': [{'id': 'thr_11111111', 'modelProvider': 'openai'}, {'id': 'thr_22222222', 'modelProvider': 'custom'}], 'nextCursor': 'next'}
        with self.server(handler): result = history.list_threads(pathlib.Path('.'), {})
        self.assertEqual(calls[0][0], 'thread/list')
        self.assertEqual(calls[0][1]['modelProviders'], [])
        self.assertTrue(calls[0][1]['useStateDbOnly'])
        self.assertEqual(len(result['threads']), 2)

    def test_preview_reads_visible_messages_and_does_not_decode_encrypted_reasoning(self):
        def handler(method, params):
            if method == 'thread/read': return {'thread': {'modelProvider': 'custom'}}
            return {'data': [{'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': 'hello'}]},
                                        {'type': 'agentMessage', 'text': 'world'},
                                        {'type': 'reasoning', 'encrypted_content': 'not-readable'}]}]}
        with self.server(handler): result = history.read_thread(pathlib.Path('.'), {'id': 'thr_11111111'})
        self.assertEqual([m['text'] for m in result['messages']], ['hello', 'world'])
        self.assertNotIn('not-readable', json.dumps(result))

    def test_native_fork_uses_current_model_and_keeps_original_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            (home / 'config.toml').write_text('model = "deepseek-test"\nmodel_provider = "cx_test"\n')
            calls = []
            def handler(method, params):
                calls.append((method, params)); return {'thread': {'id': 'thr_new11111', 'modelProvider': 'cx_test'}}
            with self.server(handler): result = history.fork_thread(home, {'id': 'thr_old11111'})
            self.assertEqual(result['forkedFromId'], 'thr_old11111')
            self.assertEqual(calls[0][1]['model'], 'deepseek-test')
            self.assertEqual(calls[0][1]['modelProvider'], 'cx_test')
            self.assertEqual(calls[0][0], 'thread/fork')


if __name__ == '__main__': unittest.main()
