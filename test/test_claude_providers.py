import copy
import contextlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from claude_providers import ClaudeProviders
from provider_key import read_key
from providers import read_bytes


class ClaudeProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'claude'
        self.home.mkdir()
        self.cc = self.root / 'cc-switch'
        self.store = ClaudeProviders(self.root / 'accounts', self.home, self.cc)
        self.original = {'env': {'KEEP': 'unchanged'}, 'permissions': {'deny': ['Read(secret)']},
                         'hooks': {'Stop': []}, 'includeCoAuthoredBy': False}
        self.store.config.write_text(json.dumps(self.original), encoding='utf-8')

    def save(self, **kw):
        payload = {'name': 'fixture', 'baseUrl': 'https://example.invalid/anthropic', 'model': 'deepseek-fixture',
                   'authType': 'token', 'apiKey': 'fixture-secret', **kw}
        result = self.store.save(payload)
        return result['savedId']

    def read(self):
        return json.loads(self.store.config.read_text(encoding='utf-8'))

    def test_switch_and_restore_preserve_unrelated_settings_and_codex(self):
        codex = self.root / 'codex' / 'config.toml'
        codex.parent.mkdir()
        codex.write_text('model = "fixture"\n', encoding='utf-8')
        before = codex.read_bytes()
        saved = self.save(sonnetModel='sonnet-fixture', opusModel='opus-fixture')
        self.store.activate(saved)
        doc = self.read()
        self.assertEqual(doc['model'], 'deepseek-fixture')
        self.assertEqual(doc['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'sonnet-fixture')
        self.assertEqual(doc['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'deepseek-fixture')
        self.assertEqual(doc['env']['ANTHROPIC_AUTH_TOKEN'], 'fixture-secret')
        doc['newPreference'] = True
        self.store.config.write_text(json.dumps(doc), encoding='utf-8')
        self.store.restore()
        self.assertEqual(self.read(), {**self.original, 'newPreference': True})
        self.assertEqual(codex.read_bytes(), before)

    def test_active_edit_applies_new_key_and_clears_old_auth_mode(self):
        saved = self.save()
        self.store.activate(saved)
        self.save(id=saved, apiKey='fixture-replaced', authType='apiKey')
        env = self.read()['env']
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
        self.assertEqual(env['ANTHROPIC_API_KEY'], 'fixture-replaced')
        self.assertEqual(read_key(self.store.root, saved), 'fixture-replaced')
        snapshot = json.dumps(self.store.snapshot())
        self.assertNotIn('fixture-replaced', snapshot)
        self.assertNotIn('fixture-secret', snapshot)

    def test_blank_key_keeps_secret_and_invalid_values_do_not_write(self):
        saved = self.save()
        self.store.activate(saved)
        self.save(id=saved, apiKey='', model='new-model')
        self.assertEqual(self.read()['env']['ANTHROPIC_AUTH_TOKEN'], 'fixture-secret')
        before = self.store.config.read_bytes()
        with self.assertRaises(ValueError):
            self.save(id=saved, baseUrl='http://remote.invalid', apiKey='bad')
        self.assertEqual(self.store.config.read_bytes(), before)

    def test_import_current_preserves_config_bytes_and_aliases(self):
        doc = {**self.original, 'env': {'ANTHROPIC_BASE_URL': 'https://example.invalid',
              'ANTHROPIC_AUTH_TOKEN': 'fixture-secret', 'ANTHROPIC_MODEL': 'custom-model',
              'ANTHROPIC_DEFAULT_OPUS_MODEL': 'custom-opus', 'KEEP': 'yes'}}
        self.store.config.write_text(json.dumps(doc, indent=4), encoding='utf-8')
        before = self.store.config.read_bytes()
        result = self.store.import_current()
        self.assertEqual(self.store.config.read_bytes(), before)
        self.assertEqual(result['activeId'], result['savedId'])
        self.assertEqual(result['providers'][0]['opusModel'], 'custom-opus')
        self.assertNotIn('fixture-secret', json.dumps(result))

    def test_cc_switch_import_is_read_only_skips_official_and_is_idempotent(self):
        self.cc.mkdir()
        db = self.cc / 'cc-switch.db'
        doc = {'env': {'ANTHROPIC_BASE_URL': 'https://example.invalid', 'ANTHROPIC_AUTH_TOKEN': 'fixture-secret',
                       'ANTHROPIC_MODEL': 'fixture-model', 'ANTHROPIC_DEFAULT_SONNET_MODEL': 'fixture-sonnet'}}
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, settings_config TEXT)')
            connection.executemany('INSERT INTO providers VALUES (?,?,?,?)', [
                ('one', 'claude', 'CC fixture', json.dumps(doc)), ('official', 'claude', 'Official', '{}'),
                ('codex', 'codex', 'Ignored', json.dumps(doc))])
        connection.close()
        before_db, before_config = db.read_bytes(), self.store.config.read_bytes()
        result = self.store.import_cc_switch()
        self.assertEqual((result['imported'], result['skipped']), (1, 1))
        again = self.store.import_cc_switch()
        self.assertEqual(len(again['providers']), 1)
        self.assertEqual(again['providers'][0]['sonnetModel'], 'fixture-sonnet')
        self.assertEqual(db.read_bytes(), before_db)
        self.assertEqual(self.store.config.read_bytes(), before_config)

    def test_external_edits_stop_switch_and_restore_keeps_new_preferences(self):
        first, second = self.save(), self.save(name='second')
        self.store.activate(first)
        doc = self.read()
        doc['env']['ANTHROPIC_BASE_URL'] = 'https://external.invalid'
        doc['unrelated'] = 'retain'
        self.store.config.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '外部修改'):
            self.store.activate(second)
        self.store.restore(force=True)
        self.assertEqual(self.read()['unrelated'], 'retain')
        self.assertEqual(self.read()['env'], self.original['env'])

    def test_delete_refuses_active_and_restoration_allows_delete(self):
        saved = self.save()
        self.store.activate(saved)
        with self.assertRaises(ValueError):
            self.store.delete(saved)
        self.store.restore()
        self.store.delete(saved)
        self.assertFalse(self.store.secret_path(saved).exists())

    def test_write_failure_rolls_back_new_key_config_and_registry(self):
        saved = self.save()
        self.store.activate(saved)
        files = [self.store.config, self.store.registry, self.store.secret_path(saved), self.store.state_path]
        before = {f: read_bytes(f) for f in files}
        import providers
        real = providers.atomic_write
        def fail_config(path, data):
            if path == self.store.config:
                raise OSError('fixture')
            return real(path, data)
        with patch.object(providers, 'atomic_write', side_effect=fail_config):
            with self.assertRaises(OSError):
                self.save(id=saved, apiKey='new-fixture-secret')
        self.assertEqual({f: read_bytes(f) for f in files}, before)

    def test_native_messages_path_auth_and_safe_errors(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            status = 200
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, self.headers.get('x-api-key'), self.headers.get('Authorization'), data))
                self.send_response(self.status)
                self.end_headers()
                self.wfile.write(json.dumps({'type': 'message', 'content': [{'type': 'text', 'text': 'OK'}]}).encode())
            def log_message(self, *args): pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:' + str(server.server_port)
        for suffix, auth in [('', 'token'), ('/v1', 'apiKey')]:
            saved = self.save(baseUrl=url + suffix, authType=auth)
            result = self.store.test_connection({'id': saved})
            self.assertTrue(result['ok'])
            self.assertEqual(seen[-1][0], '/v1/messages')
            self.assertEqual(seen[-1][1 if auth == 'apiKey' else 2], 'fixture-secret' if auth == 'apiKey' else 'Bearer fixture-secret')
            self.assertNotIn('fixture-secret', json.dumps(result))
            self.assertEqual(seen[-1][3]['max_tokens'], 32)
        Handler.status = 401
        with self.assertRaisesRegex(ValueError, 'HTTP 401'):
            self.store.test_connection({'id': saved})

    def test_missing_or_invalid_settings_not_silently_overwritten(self):
        self.store.config.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(ValueError): self.store.snapshot()
        self.assertEqual(self.store.config.read_text(), '{invalid')
        self.store.config.unlink()
        saved = self.save()
        self.store.activate(saved)
        self.store.restore()
        self.assertFalse(self.store.config.exists())


if __name__ == '__main__':
    unittest.main()
