#!/usr/bin/env python3
"""Device-code login for a numbered local Codex account, without selecting it."""

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from quota_status import QuotaError, backend_command, child_environment, identity


ROOT = pathlib.Path.home() / '.codex-accounts'
DEFAULT = pathlib.Path.home() / '.codex/auth.json'
EMAILS = {
    '1': 'wangxin031220@gmail.com',
    '2': 'KadynLedue381417@outlook.fr',
    '3': 'shuiwangsanjin@gmail.com',
}


def replace_file(source, destination):
    fd, name = tempfile.mkstemp(prefix='.login-auth-', dir=str(destination.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        for attempt in range(6):
            try:
                os.replace(name, destination)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.15)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def slot(auth):
    if auth:
        return next((i for i, email in EMAILS.items()
                     if email.lower() == (auth.get('email') or '').lower()), None)
    return None


def refreshed_at(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig')).get('last_refresh')
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def save_current():
    current = identity(DEFAULT.parent)
    number = slot(current)
    if number:
        target = ROOT / number / 'auth.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        if (DEFAULT.resolve() != target.resolve()
                and (not target.exists() or refreshed_at(DEFAULT) >= refreshed_at(target))
                and (not target.exists() or DEFAULT.read_bytes() != target.read_bytes())):
            replace_file(DEFAULT, target)
    return number


def backup(path, directory):
    if path.is_file():
        name = path.parent.name + '-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json'
        copy = directory / name
        shutil.copyfile(path, copy)
        copy.chmod(0o600)


def login(number):
    if number not in EMAILS:
        raise ValueError('Choose account 1, 2, or 3.')
    ROOT.mkdir(parents=True, exist_ok=True)
    selected = save_current()
    print('Authorize account ' + number + ': ' + EMAILS[number], flush=True)
    print('Choose this email in your browser. The plugin account will not be switched.', flush=True)
    if selected == number:
        print('This is the selected plugin account: finish its tasks first, then reload VS Code after login.', flush=True)
    # Authenticate into a new home; failure/wrong browser identity cannot damage
    # an existing numbered login or the plugin's default auth file.
    with tempfile.TemporaryDirectory(prefix='.login-' + number + '-', dir=str(ROOT)) as temporary:
        staging = pathlib.Path(temporary)
        staging.chmod(0o700)
        (staging / 'config.toml').write_text(
            'cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n', encoding='utf-8')
        command = backend_command() + [
            '-c', 'cli_auth_credentials_store="file"',
            '-c', 'forced_login_method="chatgpt"',
            'login', '--device-auth',
        ]
        completed = subprocess.run(command, env=child_environment(staging))
        auth = identity(staging)
        if completed.returncode != 0 or auth is None:
            raise ValueError('Login did not complete. Retry: cx-login ' + number)
        if slot(auth) != number:
            raise ValueError('Browser signed in as ' + str(auth.get('email'))
                             + '; expected ' + EMAILS[number]
                             + '. Existing credentials were preserved. Retry: cx-login ' + number)
        target = ROOT / number / 'auth.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        backups = ROOT / 'login-backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        # Keep the account chosen at completion; the user may have switched
        # while completing the browser flow.
        active = slot(identity(DEFAULT.parent))
        backup(target, backups)
        if active == number and DEFAULT.resolve() != target.resolve():
            backup(DEFAULT, backups)
        replace_file(staging / 'auth.json', target)
        if active == number and DEFAULT.resolve() != target.resolve():
            replace_file(target, DEFAULT)
    print('Account ' + number + ' authorized: ' + EMAILS[number])
    print('Plugin account selection preserved. Run cx status to check quota.')
    if active == number:
        print('Reload VS Code: Ctrl+Shift+P -> Developer: Reload Window')
    else:
        print('To select this account later: cx ' + number + ', then reload VS Code.')


def main():
    args = sys.argv[1:]
    if args in (['--help'], ['-h']):
        print('Usage: cx-login <1|2|3>')
        for number, email in EMAILS.items():
            print('  cx-login ' + number + '  ' + email)
        print('Complete the device-code flow in your local browser. No plugin account switch.')
        return 0
    if len(args) != 1 or args[0] not in EMAILS:
        print('Usage: cx-login <1|2|3>', file=sys.stderr)
        return 2
    login(args[0])
    return 0


if __name__ == '__main__':
    os.umask(0o077)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nLogin cancelled; existing credentials preserved.', file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, QuotaError) as error:
        print('cx-login: ' + str(error), file=sys.stderr)
        sys.exit(1)
