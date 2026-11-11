"""Bounded stdio client for documented local Codex app-server APIs."""
import json
import os
import queue
import signal
import subprocess
import threading
import time

import quota_status as quota


class RpcError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class AppServer:
    def __init__(self, home, overrides=None, timeout=35):
        command = list(quota.backend_command())
        settings = {'features.plugins': False, 'features.remote_plugin': False,
                    'features.apps': False, 'features.daemon_auto_start': False,
                    'features.api_key_model_discovery': False, 'analytics.enabled': False}
        settings.update(overrides or {})
        for key, value in settings.items(): command += ['-c', key + '=' + json.dumps(value)]
        command += ['app-server']
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env=quota.child_environment(home), cwd=str(home), text=True, encoding='utf-8', **options)
        self.messages = queue.Queue()
        self.timeout = timeout
        self.number = 0
        def read():
            try:
                for line in self.process.stdout:
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict) and 'id' in data and ('result' in data or 'error' in data): self.messages.put(data)
                    except ValueError: pass
            finally: self.messages.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'cx_accounts', 'version': '0.3.0'}})
            self.process.stdin.write('{"method":"initialized"}\n')
            self.process.stdin.flush()
        except Exception:
            self.close()
            raise

    def call(self, method, params=None):
        self.number += 1
        try:
            self.process.stdin.write(json.dumps({'id': self.number, 'method': method, 'params': params or {}}) + '\n')
            self.process.stdin.flush()
        except OSError:
            raise ValueError('Codex 后端已退出，请检查版本和配置。')
        deadline = time.monotonic() + self.timeout
        while True:
            try: message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty: raise ValueError('Codex 本地接口响应超时，请稍后重试。')
            if message is None: raise ValueError('Codex 后端无法启动，请检查配置和版本。')
            if message.get('id') != self.number: continue
            if 'error' in message:
                error = message['error']
                kind = (error.get('data') or {}).get('type') if isinstance(error.get('data'), dict) else None
                if kind == 'modelProviderMismatch':
                    raise RpcError(error.get('code'), '会话接入与当前供应商不同，请创建当前接入分支后继续。')
                raise RpcError(error.get('code'), 'Codex 无法读取或继续该会话；原始记录保持不变。请检查客户端版本及会话是否可用。')
            return message.get('result') or {}

    def close(self):
        try: self.process.stdin.close()
        except (OSError, ValueError): pass
        # EOF lets native thread/fork writers flush their new records before exit.
        try: self.process.wait(timeout=3)
        except subprocess.TimeoutExpired: pass
        if self.process.poll() is None:
            if os.name == 'nt': self.process.terminate()
            else:
                try: os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        try: self.process.wait(timeout=2)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=2)
        self.reader.join(timeout=1)
        self.process.stdout.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
