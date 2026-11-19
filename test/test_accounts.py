import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
import bridge
import providers
from account_registry import AccountRegistry


def credential(email, number='4'):
    claims = base64.urlsafe_b64encode(json.dumps({'email': email}).encode()).decode().rstrip('=')
    return json.dumps({'last_refresh': '2026-11-19T00:00:00Z', 'tokens': {
        'id_token': 'fixture.' + claims + '.fixture', 'refresh_token': 'fixture-refresh-private', 'account_id': 'account-' + number}}).encode()


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.seeds = {str(n): 'fixture' + str(n) + '@example.invalid' for n in range(1, 4)}
        for name, value in [('ROOT', self.root / 'accounts'), ('DEFAULT', self.root / 'codex/auth.json'), ('EMAILS', dict(self.seeds))]:
            patch = mock.patch.object(bridge.login, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.store = AccountRegistry(bridge.login.ROOT, self.seeds)
        bridge.login.DEFAULT.parent.mkdir()
        bridge.login.DEFAULT.write_bytes(credential(self.seeds['3'], '3'))
        for number, email in self.seeds.items():
            target = bridge.login.ROOT / number / 'auth.json'
            target.parent.mkdir(parents=True)
            target.write_bytes(credential(email, number))

    def test_legacy_slots_are_preserved_without_creating_metadata_on_read(self):
        before = bridge.login.DEFAULT.read_bytes()
        self.assertEqual([a['id'] for a in bridge.snapshot()['accounts']], ['1', '2', '3'])
        self.assertFalse(self.store.path.exists())
        self.assertEqual(bridge.login.DEFAULT.read_bytes(), before)

    def test_add_select_and_quota_query_support_new_number(self):
        before = bridge.login.DEFAULT.read_bytes()
        number = self.store.add('new@example.invalid')
        self.assertEqual(number, '4')
        data = bridge.snapshot()
        self.assertEqual(data['selected'], '3')
        self.assertFalse(data['accounts'][3]['saved'])
        self.assertEqual(bridge.login.DEFAULT.read_bytes(), before)
        target = bridge.login.ROOT / number / 'auth.json'
        target.parent.mkdir()
        target.write_bytes(credential('new@example.invalid'))
        self.assertEqual(bridge.select(number)['selected'], number)
        with mock.patch.object(bridge.quota, 'backend_command', return_value=['fixture']), mock.patch.object(bridge.quota, 'fetch_limits', return_value={'weekly': {'remaining': 42}}):
            queried = bridge.status()
        self.assertEqual(len(queried['accounts']), 4)
        self.assertEqual(queried['accounts'][3]['quota']['weekly']['remaining'], 42)

    def test_duplicate_invalid_email_and_path_traversal_leave_storage_untouched(self):
        for email in ['fixture1@EXAMPLE.invalid', 'bad', 'name@host', 'a\n@example.invalid', '', None]:
            with self.assertRaises(ValueError): self.store.add(email)
        self.assertFalse(self.store.path.exists())
        for number in ['../1', '/tmp/target', '0', '01', None]:
            with self.assertRaises(ValueError): self.store.remove(number, bridge.login.DEFAULT, self.seeds['3'])

    def test_remove_archives_credentials_and_deleted_seed_does_not_reappear(self):
        target = bridge.login.ROOT / '1/auth.json'
        old = target.read_bytes()
        backup = self.store.remove('1', bridge.login.DEFAULT, self.seeds['3'], self.seeds['1'])
        self.assertFalse(target.exists())
        self.assertEqual((pathlib.Path(backup) / 'auth.json').read_bytes(), old)
        self.assertNotIn('1', self.store.emails())
        self.assertEqual([a['id'] for a in bridge.snapshot()['accounts']], ['2', '3'])
        self.assertNotIn('fixture-refresh-private', self.store.path.read_text())
        self.assertEqual(bridge.snapshot()['selected'], '3')

    def test_current_account_and_default_symlink_are_protected(self):
        before = bridge.login.DEFAULT.read_bytes()
        with self.assertRaises(ValueError): self.store.remove('3', bridge.login.DEFAULT, self.seeds['3'])
        self.assertEqual(bridge.login.DEFAULT.read_bytes(), before)
        if os.name != 'nt':
            bridge.login.DEFAULT.unlink()
            bridge.login.DEFAULT.symlink_to(bridge.login.ROOT / '1/auth.json')
            with self.assertRaises(ValueError): self.store.remove('1', bridge.login.DEFAULT, None)
            self.assertTrue(bridge.login.DEFAULT.exists())

    def test_empty_registry_is_authoritative_and_does_not_require_backend(self):
        self.store.path.write_text(json.dumps({'version': 1, 'emails': {}, 'nextId': 4}))
        with mock.patch.object(bridge.quota, 'backend_command', side_effect=AssertionError('No account to query')):
            self.assertEqual(bridge.status()['accounts'], [])
        self.assertEqual(self.store.add('next@example.invalid'), '4')

    def test_deleted_ids_and_existing_directories_are_never_reused(self):
        number = self.store.add('four@example.invalid')
        self.store.remove(number, bridge.login.DEFAULT, self.seeds['3'])
        self.assertEqual(self.store.add('five@example.invalid'), '5')
        (bridge.login.ROOT / '6').mkdir()
        self.assertEqual(self.store.add('seven@example.invalid'), '7')

    def test_corrupt_metadata_and_stale_ui_do_not_remove_credentials(self):
        target = bridge.login.ROOT / '1/auth.json'
        with self.assertRaises(ValueError): self.store.remove('1', bridge.login.DEFAULT, self.seeds['3'], 'someone@example.invalid')
        self.assertTrue(target.exists())
        self.store.path.write_text('{broken')
        with self.assertRaises(ValueError): self.store.emails()
        self.assertEqual(self.store.path.read_text(), '{broken')

    def test_failed_removal_rolls_back_registry_and_credentials(self):
        self.store.add('four@example.invalid')
        before = self.store.path.read_bytes()
        auth = (bridge.login.ROOT / '1/auth.json').read_bytes()
        original = providers.atomic_write
        def fail_backup(path, content):
            if path.name == 'auth.json' and 'account-delete-backups' in str(path):
                raise OSError('fixture failure')
            return original(path, content)
        with mock.patch.object(providers, 'atomic_write', side_effect=fail_backup):
            with self.assertRaises(OSError): self.store.remove('1', bridge.login.DEFAULT, self.seeds['3'])
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual((bridge.login.ROOT / '1/auth.json').read_bytes(), auth)

    def test_new_account_device_login_validates_identity_and_preserves_selection(self):
        number = self.store.add('four@example.invalid')
        before = bridge.login.DEFAULT.read_bytes()
        def complete(command, env):
            (pathlib.Path(env['CODEX_HOME']) / 'auth.json').write_bytes(credential('four@example.invalid'))
            return types.SimpleNamespace(returncode=0)
        with mock.patch.object(bridge.login, 'backend_command', return_value=['fixture']), mock.patch.object(bridge.login.subprocess, 'run', side_effect=complete):
            bridge.login.login(number)
        self.assertEqual(bridge.login.DEFAULT.read_bytes(), before)
        self.assertTrue((bridge.login.ROOT / number / 'auth.json').exists())
        def wrong(command, env):
            (pathlib.Path(env['CODEX_HOME']) / 'auth.json').write_bytes(credential('wrong@example.invalid'))
            return types.SimpleNamespace(returncode=0)
        saved = (bridge.login.ROOT / number / 'auth.json').read_bytes()
        with mock.patch.object(bridge.login, 'backend_command', return_value=['fixture']), mock.patch.object(bridge.login.subprocess, 'run', side_effect=wrong):
            with self.assertRaises(ValueError): bridge.login.login(number)
        self.assertEqual((bridge.login.ROOT / number / 'auth.json').read_bytes(), saved)

    def test_real_bridge_lifecycle_returns_metadata_only(self):
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'CX_EXTENSION_OPTIONS': json.dumps({
            'accountsRoot': str(bridge.login.ROOT), 'codexHome': str(bridge.login.DEFAULT.parent), 'emails': self.seeds})}
        def call(operation, payload):
            result = subprocess.run([sys.executable, str(pathlib.Path(bridge.__file__)), operation],
                                    input=json.dumps(payload), text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('fixture-refresh-private', result.stdout)
            return json.loads(result.stdout)
        added = call('account-add', {'email': 'four@example.invalid'})
        self.assertEqual(added['addedId'], '4')
        deleted = call('account-delete', {'id': '1', 'expectedEmail': self.seeds['1']})
        self.assertEqual(deleted['deletedId'], '1')
        self.assertEqual([a['id'] for a in deleted['accounts']], ['2', '3', '4'])


if __name__ == '__main__': unittest.main()
