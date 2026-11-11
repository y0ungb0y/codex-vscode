'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function expandHome(value) {
  return value === '~' ? os.homedir() : value.startsWith('~/') || value.startsWith('~\\')
    ? path.join(os.homedir(), value.slice(2)) : value;
}

function runJson(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      shell: false, windowsHide: true, env: options.env || process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let output = '', done = false;
    const finish = (error, result) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      error ? reject(error) : resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(new Error('查询超时，请检查代理或 SSH 隧道。'));
    }, options.timeout || 45000);
    child.stdout.on('data', data => {
      output += data.toString('utf8');
      if (output.length > 1024 * 1024) {
        child.kill();
        finish(new Error('后端返回数据异常。'));
      }
    });
    // Do not display subprocess stderr: it may include sensitive account data.
    child.stderr.on('data', () => {});
    child.stdin.on('error', () => {});
    child.stdin.end(options.input ? JSON.stringify(options.input) : undefined);
    child.on('error', () => finish(new Error('无法启动 Python，请在 CX 设置中填写 Python 可执行文件路径。')));
    child.on('close', code => {
      if (done) return;
      try {
        const result = JSON.parse(output.trim());
        if (result.error) return finish(new Error(result.error));
        if (code !== 0) return finish(new Error('账号操作失败。'));
        finish(null, result);
      } catch {
        finish(new Error('无法读取账号信息，请检查 Python 版本（需要 3.8+）和 CX 设置。'));
      }
    });
  });
}

class Client {
  constructor(extensionPath, getOptions) {
    this.bridge = path.join(extensionPath, 'python', 'bridge.py');
    this.getOptions = getOptions;
    this.python = null;
    this.pythonSetting = null;
  }
  environment() {
    const opts = this.getOptions();
    return { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1',
      CX_EXTENSION_OPTIONS: JSON.stringify({
        accountsRoot: expandHome(opts.accountsRoot || ''), codexHome: expandHome(opts.codexHome || ''),
        codexPath: expandHome(opts.codexPath || ''), proxyUrl: opts.proxyUrl || '', emails: opts.emails,
        claudeHome: expandHome(opts.claudeHome || ''), ccSwitchHome: expandHome(opts.ccSwitchHome || ''),
      }) };
  }
  async interpreter() {
    const setting = this.getOptions().pythonPath || '';
    if (this.python && this.pythonSetting === setting) return this.python;
    const candidates = setting ? [[expandHome(setting)]] : process.platform === 'win32' ? [
      [path.join(os.homedir(), 'miniconda3', 'python.exe')],
      [path.join(os.homedir(), 'anaconda3', 'python.exe')],
      ['D:\\miniconda\\python.exe'], ['python'], ['py', '-3'],
    ] : [['python3'], ['python']];
    for (const candidate of candidates) {
      if (path.isAbsolute(candidate[0]) && !fs.existsSync(candidate[0])) continue;
      try {
        const result = await runJson(candidate[0], [...candidate.slice(1), '-c',
          'import sys,json;print(json.dumps({"ok":sys.version_info>=(3,8)}))'], { timeout: 4000 });
        if (result.ok) {
          this.python = candidate; this.pythonSetting = setting;
          return candidate;
        }
      } catch { /* try the next interpreter */ }
    }
    throw new Error('未找到 Python 3.8+，请在 CX 设置中填写 Python 路径。');
  }
  async request(operation, number) {
    if (!['snapshot', 'status', 'select'].includes(operation)) throw new Error('无效的账号操作。');
    if (operation === 'select' && !['1', '2', '3'].includes(number)) throw new Error('无效的账号编号。');
    const python = await this.interpreter();
    return runJson(python[0], [...python.slice(1), this.bridge, operation, ...(number ? [number] : [])],
      { env: this.environment(), timeout: operation === 'status' ? 45000 : 10000 });
  }
  async loginTerminalOptions(number) {
    if (!['1', '2', '3'].includes(number)) throw new Error('无效的账号编号。');
    const python = await this.interpreter();
    return {
      name: `CX 授权 · 账号 ${number}`, shellPath: python[0],
      shellArgs: [...python.slice(1), this.bridge, 'login', number], env: this.environment(),
      isTransient: true,
    };
  }
  async providerRequest(operation, payload = {}) {
    if (!['save', 'select', 'delete', 'restore', 'import', 'models'].includes(operation)) throw new Error('无效的供应商操作。');
    const python = await this.interpreter();
    return runJson(python[0], [...python.slice(1), this.bridge, `provider-${operation}`],
      { env: this.environment(), input: payload, timeout: operation === 'models' ? 25000 : 15000 });
  }
  async claudeRequest(operation, payload = {}) {
    if (!['snapshot', 'save', 'select', 'delete', 'restore', 'import', 'import-cc', 'models', 'test'].includes(operation)) throw new Error('无效的 Claude 供应商操作。');
    const python = await this.interpreter();
    return runJson(python[0], [...python.slice(1), this.bridge, `claude-${operation}`],
      { env: this.environment(), input: payload, timeout: operation === 'test' ? 35000 : 15000 });
  }
  async historyRequest(operation, payload = {}) {
    if (!['list', 'read', 'fork'].includes(operation)) throw new Error('无效的会话操作。');
    const python = await this.interpreter();
    return runJson(python[0], [...python.slice(1), this.bridge, `history-${operation}`],
      { env: this.environment(), input: payload, timeout: 45000 });
  }
}

module.exports = { Client, runJson, expandHome };
