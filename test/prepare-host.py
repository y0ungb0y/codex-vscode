import base64
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[1] / '.test-vscode'
user = root / 'user'
settings_dir = user / 'User'
settings_dir.mkdir(parents=True, exist_ok=True)
emails = {'1': 'one@example.invalid', '2': 'two@example.invalid', '3': 'three@example.invalid'}
for number, email in emails.items():
    home = root / 'accounts' / number
    home.mkdir(parents=True, exist_ok=True)
    payload = base64.urlsafe_b64encode(json.dumps({'email': email}).encode()).decode().rstrip('=')
    auth = {'last_refresh': '2026-11-11T00:00:00Z', 'tokens': {
        'account_id': 'fixture-' + number, 'id_token': 'test.' + payload + '.test', 'refresh_token': 'fake-test-fixture'}}
    (home / 'auth.json').write_text(json.dumps(auth), encoding='utf-8')
home = root / 'codex'
home.mkdir(exist_ok=True)
(home / 'auth.json').write_bytes((root / 'accounts/3/auth.json').read_bytes())
claude_home = root / 'claude'
claude_home.mkdir(exist_ok=True)
(claude_home / 'settings.json').write_text('{}', encoding='utf-8')
(settings_dir / 'settings.json').write_text(json.dumps({
    'cxAccounts.pythonPath': sys.executable,
    'cxAccounts.codexPath': sys.executable,
    'cxAccounts.accountsRoot': str(root / 'accounts'),
    'cxAccounts.codexHome': str(home),
    'cxAccounts.claudeHome': str(claude_home),
    'cxAccounts.emails': emails,
    'cxAccounts.autoRefresh': False,
    'security.workspace.trust.enabled': False,
    'workbench.startupEditor': 'none',
    'update.mode': 'none',
    'extensions.autoCheckUpdates': False,
    'telemetry.telemetryLevel': 'off',
}), encoding='utf-8')
(root / 'extensions').mkdir(exist_ok=True)
(root / 'workspace').mkdir(exist_ok=True)
print(root)
