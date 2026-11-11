"""JSON-only bridge for the VS Code extension; credentials never cross stdout."""
import concurrent.futures
import contextlib
import datetime
import importlib.util
import json
import os
import pathlib
import sys

import login_account as login
import quota_status as quota
from providers import Providers
import history
import model_catalog
from claude_providers import ClaudeProviders


def provider_store():
    return Providers(login.ROOT, login.DEFAULT.parent)


def configure():
    options = json.loads(os.environ.get('CX_EXTENSION_OPTIONS', '{}'))
    login.ROOT = pathlib.Path(options.get('accountsRoot') or pathlib.Path.home() / '.codex-accounts').expanduser()
    login.DEFAULT = pathlib.Path(options.get('codexHome') or os.environ.get('CODEX_HOME') or pathlib.Path.home() / '.codex').expanduser() / 'auth.json'
    emails = options.get('emails') or login.EMAILS
    if set(emails) != {'1', '2', '3'} or any(not isinstance(e, str) or '@' not in e for e in emails.values()):
        raise ValueError('Invalid account email settings')
    login.EMAILS = emails
    command = options.get('codexPath')
    if command:
        executable = pathlib.Path(command).expanduser()
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError('Configured Codex executable does not exist')
        quota.backend_command = lambda: [str(executable)]
        login.backend_command = quota.backend_command
    proxy = options.get('proxyUrl')
    if proxy:
        if not proxy.startswith(('http://', 'https://', 'socks5://', 'socks5h://')):
            raise ValueError('Invalid proxy URL')
        original_environment = quota.child_environment

        def environment(home):
            env = original_environment(home)
            for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'CX_PROXY_URL'):
                env[key] = proxy
            return env
        quota.child_environment = environment
        login.child_environment = environment


class OperationLock:
    """Coordinate overlapping plugin windows on the same machine/user."""
    def __enter__(self):
        login.ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.stream = (login.ROOT / '.cx-extension.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b'0')
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError('Another CX window is refreshing or authorizing accounts; retry shortly')
        return self

    def __exit__(self, *args):
        self.stream.close()


def snapshot():
    selected = login.save_current()
    current = quota.identity(login.DEFAULT.parent)
    return {
        'providerState': provider_store().snapshot(),
        'selected': selected,
        'currentEmail': current.get('email') if current else None,
        'accounts': [
            {'id': number, 'email': email,
             'saved': login.slot(quota.identity(login.ROOT / number)) == number,
             'selected': number == selected}
            for number, email in login.EMAILS.items()
        ],
        'updatedAt': datetime.datetime.now(quota.TIMEZONE).isoformat(),
    }


def status():
    data = snapshot()
    by_id = {a['id']: a for a in data['accounts']}
    jobs = []
    for number, email in login.EMAILS.items():
        home = login.DEFAULT.parent if number == data['selected'] else login.ROOT / number
        auth = quota.identity(home)
        if not auth:
            by_id[number]['error'] = 'not signed in locally'
        elif (auth.get('email') or '').lower() != email.lower():
            by_id[number]['error'] = 'stored login email mismatch; not queried'
        else:
            jobs.append((number, home, auth['account_id']))
    command = quota.backend_command()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(quota.fetch_limits, home, account_id, command): n for n, home, account_id in jobs}
            for future in concurrent.futures.as_completed(futures):
                account = by_id[futures[future]]
                try:
                    account['quota'] = future.result()
                except quota.QuotaError as error:
                    account['error'] = str(error)
                except Exception as error:
                    account['error'] = quota.safe_error(error)
    finally:
        login.save_current()
    return data


def select(number):
    if number not in login.EMAILS or login.slot(quota.identity(login.ROOT / number)) != number:
        raise ValueError('Account is not signed in with the expected email; authorize it first')
    with provider_store().account_mode():
        return select_account(number)


def select_account(number):
    if number not in login.EMAILS:
        raise ValueError('Choose account 1, 2, or 3')
    target = login.ROOT / number / 'auth.json'
    if login.slot(quota.identity(target.parent)) != number:
        raise ValueError('Account is not signed in with the expected email; authorize it first')
    login.save_current()
    login.DEFAULT.parent.mkdir(parents=True, exist_ok=True)
    directory = login.ROOT / 'plugin-switch-backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    if login.DEFAULT.exists() and login.DEFAULT.read_bytes() != target.read_bytes():
        login.backup(login.DEFAULT, directory)
    if os.name == 'nt':
        if not login.DEFAULT.exists() or login.DEFAULT.read_bytes() != target.read_bytes():
            login.replace_file(target, login.DEFAULT)
    else:
        # Match cx-ide's existing symlink design, without assuming it is installed.
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix='.cx-link-', dir=str(login.DEFAULT.parent))
        os.close(fd)
        os.unlink(temporary)
        try:
            os.symlink(str(target.resolve()), temporary)
            os.replace(temporary, login.DEFAULT)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)
    return snapshot()


def main():
    configure()
    args = sys.argv[1:]
    if args and args[0].startswith('claude-'):
        operations = ('snapshot', 'save', 'select', 'delete', 'restore', 'import', 'import-cc', 'models', 'test')
        operation = args[0][len('claude-'):]
        if len(args) != 1 or operation not in operations:
            raise ValueError('Unsupported Claude operation')
        options = json.loads(os.environ.get('CX_EXTENSION_OPTIONS', '{}'))
        store = ClaudeProviders(login.ROOT, pathlib.Path(options.get('claudeHome') or os.environ.get('CLAUDE_CONFIG_DIR') or pathlib.Path.home() / '.claude').expanduser(), options.get('ccSwitchHome'))
        payload = json.loads(sys.stdin.read(65537) or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Claude 供应商表单无效。')
        with OperationLock():
            if operation == 'snapshot': result = store.snapshot()
            elif operation == 'save': result = store.save(payload)
            elif operation == 'select': result = store.activate(payload.get('id'))
            elif operation == 'delete': result = store.delete(payload.get('id'))
            elif operation == 'restore': result = store.restore(force=True)
            elif operation == 'import': result = store.import_current()
            elif operation == 'import-cc': result = store.import_cc_switch()
            elif operation == 'models': result = store.models(payload)
            else: result = store.test_connection(payload)
            print(json.dumps(result, ensure_ascii=True))
        return
    operations = ('snapshot', 'status', 'select', 'login', 'provider-save', 'provider-select', 'provider-delete', 'provider-restore', 'provider-import', 'provider-models', 'history-list', 'history-read', 'history-fork')
    if not args or args[0] not in operations:
        raise ValueError('Unsupported operation')
    if args[0] in ('select', 'login') and (len(args) != 2 or args[1] not in login.EMAILS):
        raise ValueError('Choose account 1, 2, or 3')
    if args[0] in ('snapshot', 'status') and len(args) != 1:
        raise ValueError('Unsupported arguments')
    with OperationLock():
        if args[0].startswith('history-'):
            if len(args) != 1: raise ValueError('Unsupported arguments')
            payload = json.loads(sys.stdin.read(65537))
            if not isinstance(payload, dict): raise ValueError('会话参数无效。')
            handler = {'history-list': history.list_threads, 'history-read': history.read_thread, 'history-fork': history.fork_thread}[args[0]]
            print(json.dumps(handler(login.DEFAULT.parent, payload), ensure_ascii=True))
            return
        if args[0].startswith('provider-'):
            if len(args) != 1:
                raise ValueError('Unsupported arguments')
            payload = json.loads(sys.stdin.read(65537))
            if not isinstance(payload, dict): raise ValueError('供应商表单无效。')
            store = provider_store()
            if args[0] == 'provider-save': result = store.save(payload)
            elif args[0] == 'provider-select': result = store.activate(payload.get('id'))
            elif args[0] == 'provider-delete': result = store.delete(payload.get('id'))
            elif args[0] == 'provider-import': result = store.import_current()
            elif args[0] == 'provider-models': result = model_catalog.discover(store, payload)
            else: result = store.restore(force=True)
            print(json.dumps(result, ensure_ascii=True))
            return
        if args[0] == 'login':
            login.login(args[1])
            return
        result = {'snapshot': snapshot, 'status': status}.get(args[0])
        data = result() if result else select(args[1])
        print(json.dumps(data, ensure_ascii=True))


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        # Never serialize raw subprocess stderr, auth.json, JWTs or RPC payloads.
        known = isinstance(error, (ValueError, quota.QuotaError))
        print(json.dumps({'error': str(error) if known else 'Account operation failed; check paths and permissions'}))
        sys.exit(1)
