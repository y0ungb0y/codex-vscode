import base64
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
import bridge


def fixture(number, email=None, version='old'):
    payload = base64.urlsafe_b64encode(json.dumps({'email': email or bridge.login.EMAILS[number]}).encode()).decode().rstrip('=')
    return json.dumps({'last_refresh': '2026-11-11T00:00:00Z', 'tokens': {
        'account_id': 'test-' + number, 'id_token': 'test.' + payload + '.test', 'refresh_token': version}}).encode()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.patch_root = mock.patch.object(bridge.login, 'ROOT', self.root / 'accounts')
        self.patch_default = mock.patch.object(bridge.login, 'DEFAULT', self.root / 'plugin/auth.json')
        self.patch_root.start(); self.patch_default.start()
        bridge.login.DEFAULT.parent.mkdir()
        bridge.login.DEFAULT.write_bytes(fixture('3'))
        for n in ('1', '2', '3'):
            home = bridge.login.ROOT / n
            home.mkdir(parents=True)
            (home / 'auth.json').write_bytes(fixture(n))

    def tearDown(self):
        self.patch_default.stop(); self.patch_root.stop(); self.temp.cleanup()

    def test_snapshot_never_exports_credentials(self):
        data = bridge.snapshot()
        self.assertEqual(data['selected'], '3')
        encoded = json.dumps(data)
        for forbidden in ('refresh_token', 'id_token', 'access_token', 'test.test'):
            self.assertNotIn(forbidden, encoded)

    def test_repeated_snapshot_does_not_rewrite_equal_credentials(self):
        account_file = bridge.login.ROOT / '3/auth.json'
        before = account_file.stat().st_mtime_ns
        bridge.snapshot()
        bridge.snapshot()
        self.assertEqual(account_file.stat().st_mtime_ns, before)

    def test_select_and_wrong_identity(self):
        self.assertEqual(bridge.select('1')['selected'], '1')
        (bridge.login.ROOT / '2/auth.json').write_bytes(fixture('1'))
        before = bridge.login.DEFAULT.read_bytes()
        with self.assertRaises(ValueError): bridge.select('2')
        self.assertEqual(before, bridge.login.DEFAULT.read_bytes())

    def test_status_does_not_switch_and_separates_account_errors(self):
        before = bridge.login.DEFAULT.read_bytes()
        def fetch(home, account_id, command):
            if account_id == 'test-2': raise bridge.quota.QuotaError('login expired or rejected; sign in again')
            return {'five_hour': {'remaining': 0, 'resets_at': None}, 'weekly': None}
        with mock.patch.object(bridge.quota, 'backend_command', return_value=['test']), mock.patch.object(bridge.quota, 'fetch_limits', side_effect=fetch):
            data = bridge.status()
        self.assertEqual(data['selected'], '3')
        self.assertEqual(data['accounts'][0]['quota']['five_hour']['remaining'], 0)
        self.assertIn('error', data['accounts'][1])
        self.assertEqual(before, bridge.login.DEFAULT.read_bytes())

    def test_cross_process_lock_is_exclusive(self):
        import subprocess
        script = "import sys,pathlib;sys.path.insert(0,sys.argv[1]);import bridge;bridge.login.ROOT=pathlib.Path(sys.argv[2]);bridge.OperationLock().__enter__()"
        with bridge.OperationLock():
            result = subprocess.run([sys.executable, '-c', script, str(pathlib.Path(bridge.__file__).parent), str(bridge.login.ROOT)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()
