"""Stable Codex credential helper. Never import this file from a workspace.

Windows uses current-user DPAPI; Unix stores keys in owner-only files. The
command's stdout is deliberately the token protocol required by Codex.
"""
import base64
import ctypes
import json
import os
import pathlib
import re
import sys
import tempfile


def check_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('供应商编号无效。')
    return value


def atomic_write(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        path.parent.chmod(0o700)
    if path.is_symlink():
        raise ValueError('配置或密钥文件是符号链接，请先改用独立文件。')
    fd, temporary = tempfile.mkstemp(prefix='.cx-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def dpapi(data, decrypt=False):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('Windows 无法加密或解密此用户的密钥。')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def encode_key(key):
    if (not isinstance(key, str) or not key.strip() or len(key) > 16384
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key)):
        raise ValueError('API Key 不能为空，且不能包含空白字符。')
    raw = key.encode('utf-8')
    mode = 'dpapi' if os.name == 'nt' else 'owner-file'
    encrypted = dpapi(raw) if mode == 'dpapi' else raw
    return json.dumps({'storage': mode, 'value': base64.b64encode(encrypted).decode('ascii')}).encode()


def read_key(root, number):
    path = pathlib.Path(root) / 'secrets' / (check_id(number) + '.json')
    if path.is_symlink() or (os.name != 'nt' and (path.stat().st_mode & 0o077)):
        raise ValueError('密钥文件权限不正确。')
    value = json.loads(path.read_text(encoding='utf-8'))
    raw = base64.b64decode(value['value'], validate=True)
    if value['storage'] == 'dpapi' and os.name == 'nt':
        raw = dpapi(raw, decrypt=True)
    elif value['storage'] != 'owner-file' or os.name == 'nt':
        raise ValueError('密钥存储不属于当前系统。')
    return raw.decode('utf-8')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('Invalid helper arguments')
        sys.stdout.write(read_key(sys.argv[1], sys.argv[2]))
    except Exception:
        print('CX credential unavailable; open CX and replace the API key.', file=sys.stderr)
        sys.exit(1)
