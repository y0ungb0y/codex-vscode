import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
import providers
import provider_key
import bridge
from test_bridge import fixture


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temp.name)
        self.store = providers.Providers(self.base / 'accounts', self.base / 'codex')
        self.original = '# user comment\nmodel = "official-model" # chosen\nmodel_provider = "openai"\nforced_login_method = "chatgpt"\n\n[mcp_servers.test]\ncommand = "keep-this" # retained\n'
        self.store.config.parent.mkdir()
        self.store.config.write_text(self.original, encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def save(self, **overrides):
        data = {'name': 'Test gateway', 'baseUrl': 'https://gateway.example.invalid/v1',
                'model': 'test-model', 'apiKey': 'fixture-key-DO-NOT-USE'}
        data.update(overrides)
        return self.store.save(data)

    def test_switch_and_official_roundtrip_preserve_other_settings_and_auth(self):
        auth = self.store.config.parent / 'auth.json'
        auth.write_bytes(fixture('3'))
        before_auth = auth.read_bytes()
        saved = self.save()
        self.assertEqual(self.store.config.read_text(), self.original)
        active = self.store.activate(saved['savedId'])
        text = self.store.config.read_text()
        self.assertIn('wire_api = "responses"', text)
        self.assertIn('keep-this', text)
        self.assertIn('# retained', text)
        self.assertNotIn('fixture-key', text)
        self.assertNotIn('forced_login_method', text)
        self.assertEqual(active['mode'], 'thirdParty')
        with mock.patch.object(bridge.login, 'ROOT', self.base / 'accounts'), mock.patch.object(bridge.login, 'DEFAULT', auth):
            for n in ('1', '2', '3'):
                directory = bridge.login.ROOT / n
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'auth.json').write_bytes(fixture(n))
            result = bridge.select('1')
        self.assertEqual(result['providerState']['mode'], 'official')
        self.assertEqual(result['selected'], '1')
        text = self.store.config.read_text()
        self.assertIn('model = "official-model"', text)
        self.assertIn('forced_login_method = "chatgpt"', text)
        self.assertIn('# retained', text)
        self.assertNotIn('cx_', text)
        self.assertEqual((self.base / 'accounts/3/auth.json').read_bytes(), before_auth)

    def test_secret_helper_can_read_key_without_key_in_metadata_or_process_arguments(self):
        saved = self.save()
        number = saved['savedId']
        self.store.activate(number)
        raw = self.store.registry.read_text()
        self.assertNotIn('fixture-key', raw)
        self.assertNotIn('fixture-key', json.dumps(self.store.snapshot()))
        result = subprocess.run([sys.executable, str(self.store.root / 'credential_helper.py'), str(self.store.root), number], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), 'fixture-key-DO-NOT-USE')
        self.assertEqual(result.stderr, b'')
        secret = self.store.secret_path(number)
        if os.name == 'nt':
            self.assertNotIn(b'fixture-key', secret.read_bytes())
            self.assertEqual(json.loads(secret.read_text())['storage'], 'dpapi')
        else:
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): provider_key.check_id('../auth')

    def test_blank_key_keeps_existing_and_active_edit_updates_config(self):
        number = self.save()['savedId']
        self.store.activate(number)
        before = self.store.secret_path(number).read_bytes()
        edited = self.save(id=number, model='new-model', apiKey='')
        self.assertTrue(edited['requiresReload'])
        self.assertIn('model = "new-model"', self.store.config.read_text())
        self.assertEqual(self.store.secret_path(number).read_bytes(), before)

    def test_delete_removes_key_but_refuses_active_provider(self):
        number = self.save()['savedId']
        self.store.activate(number)
        with self.assertRaises(ValueError): self.store.delete(number)
        self.assertTrue(self.store.secret_path(number).exists())
        self.store.restore(official=True)
        self.store.delete(number)
        self.assertFalse(self.store.secret_path(number).exists())
        self.assertEqual(self.store.snapshot()['providers'], [])

    def test_invalid_values_cannot_change_saved_credentials_or_config(self):
        number = self.save()['savedId']
        before = self.store.registry.read_bytes()
        key = self.store.secret_path(number).read_bytes()
        for data in ({'baseUrl': 'https://user:secret@example.com/v1'},
                     {'baseUrl': 'http://example.com/v1'}, {'model': 'bad\nmodel'},
                     {'baseUrl': 'https://example.com/v1?api_key=secret'}, {'apiKey': 'key\nheader'}):
            with self.assertRaises(ValueError): self.save(id=number, **data)
        self.assertEqual(self.store.registry.read_bytes(), before)
        self.assertEqual(self.store.secret_path(number).read_bytes(), key)
        self.assertEqual(self.store.config.read_text(), self.original)

    def test_bad_toml_is_preserved_and_error_contains_no_config_values(self):
        number = self.save()['savedId']
        raw = b'model = "private-config-value"\ninvalid = [\n'
        self.store.config.write_bytes(raw)
        with self.assertRaises(ValueError) as error: self.store.activate(number)
        self.assertNotIn('private-config-value', str(error.exception))
        self.assertEqual(self.store.config.read_bytes(), raw)

    def test_failed_write_rolls_back_configuration(self):
        number = self.save()['savedId']
        original_write = providers.atomic_write
        def fail_state(path, content):
            if path == self.store.state_path: raise OSError('fixture disk failure')
            original_write(path, content)
        with mock.patch.object(providers, 'atomic_write', side_effect=fail_state):
            with self.assertRaises(OSError): self.store.activate(number)
        self.assertEqual(self.store.config.read_text(), self.original)
        self.assertFalse(self.store.state_path.exists())

    def test_external_managed_edits_require_explicit_restore_other_edits_survive(self):
        number = self.save()['savedId']
        self.store.activate(number)
        text = self.store.config.read_text().replace('model = "test-model"', 'model = "external-model"')
        text = text.replace('keep-this', 'user-edit')
        self.store.config.write_text(text, encoding='utf-8')
        with self.assertRaises(ValueError): self.store.restore(official=True)
        self.store.restore(force=True)
        self.assertIn('user-edit', self.store.config.read_text())
        self.assertIn('official-model', self.store.config.read_text())

    def test_account_selection_failure_rolls_back_provider_mode(self):
        number = self.save()['savedId']
        self.store.activate(number)
        before = self.store.config.read_bytes()
        with self.assertRaises(RuntimeError):
            with self.store.account_mode(): raise RuntimeError('fixture switch failed')
        self.assertEqual(self.store.config.read_bytes(), before)
        self.assertEqual(self.store.snapshot()['activeId'], number)

    def test_config_edit_between_parse_and_commit_is_not_overwritten(self):
        number = self.save()['savedId']
        record = self.store.records()[0]
        changes = self.store.activation_changes(record)
        self.store.config.write_text(self.original + '\n# external edit\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            providers.commit(changes, {self.store.config: self.store.expected_config})
        self.assertIn('# external edit', self.store.config.read_text())
        self.assertFalse(self.store.state_path.exists())

    def test_explicit_account_selection_clears_forced_api_mode(self):
        self.store.config.write_text('model_provider = "openai"\nforced_login_method = "api"\n', encoding='utf-8')
        with self.store.account_mode(): pass
        self.assertIn('forced_login_method = "chatgpt"', self.store.config.read_text())

    def test_import_cc_switch_preserves_working_config_and_allows_official_return(self):
        catalog = self.base / 'cc-switch-model-catalog.json'
        catalog.write_text('{"models": []}')
        raw = ('model = "cc-model"\nmodel_provider = "custom"\nmodel_catalog_json = ' + json.dumps(str(catalog)) +
               '\n[model_providers.custom]\nname = "CC supplier"\nbase_url = "https://example.invalid/v1"\n'
               'wire_api = "responses"\nrequires_openai_auth = true\nexperimental_bearer_token = "cc-fixture-key"\n').encode()
        self.store.config.write_bytes(raw)
        imported = self.store.import_current()
        self.assertEqual(self.store.config.read_bytes(), raw)
        self.assertEqual(imported['activeId'], imported['savedId'])
        self.assertNotIn('cc-fixture-key', json.dumps(imported))
        self.assertNotIn('cc-fixture-key', self.store.registry.read_text())
        number = imported['savedId']
        self.assertEqual(provider_key.read_key(self.store.root, number), 'cc-fixture-key')
        self.store.import_current()
        self.assertEqual(len(self.store.records()), 1, 're-import updates rather than duplicates')
        with self.store.account_mode(): pass
        self.assertEqual(self.store.snapshot()['mode'], 'official')
        self.assertNotIn('model_catalog_json', providers.tomlkit.parse(self.store.config.read_text()))
        self.store.activate(number)
        active_catalog = pathlib.Path(providers.tomlkit.parse(self.store.config.read_text())['model_catalog_json'])
        self.assertEqual(json.loads(active_catalog.read_text(encoding='utf-8'))['models'][0]['slug'], 'cc-model')

    def test_cc_switch_external_provider_edits_are_detected(self):
        number = self.save()['savedId']
        self.store.activate(number)
        text = self.store.config.read_text().replace('https://gateway.example.invalid/v1', 'https://changed.example.invalid/v1')
        self.store.config.write_text(text, encoding='utf-8')
        with self.assertRaises(ValueError): self.store.restore(official=True)

    def test_v02_state_migrates_and_restores_newly_managed_model_parameters(self):
        number = self.save(model='deepseek-fixture')['savedId']
        doc = providers.tomlkit.parse(self.original)
        doc['model_provider'] = 'cx_' + number
        doc['model'] = 'deepseek-fixture'
        doc['model_reasoning_effort'] = 'ultra'
        doc['service_tier'] = 'fast'
        doc['web_search'] = 'cached'
        self.store.config.write_text(providers.tomlkit.dumps(doc), encoding='utf-8')
        old = {'original': self.original, 'hadFile': True, 'applied': self.store.fingerprint(doc, providers.OLD_FIELDS)}
        self.store.state_path.write_text(json.dumps(old), encoding='utf-8')
        self.store.activate(number)
        _, active = self.store.document()
        self.assertEqual(active['model_reasoning_effort'], 'low')
        self.assertNotIn('service_tier', active)
        self.assertEqual(json.loads(self.store.state_path.read_text(encoding='utf-8'))['schema'], 3)
        self.store.restore(official=True)
        _, restored = self.store.document()
        self.assertEqual(restored['model_reasoning_effort'], 'ultra')
        self.assertEqual(restored['service_tier'], 'fast')
        self.assertEqual(restored['web_search'], 'cached')


if __name__ == '__main__': unittest.main()
