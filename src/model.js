'use strict';

function remaining(window) {
  return window && Number.isFinite(window.remaining) ? `${window.remaining}%` : '未提供';
}
function reset(window) {
  if (!window || !Number.isFinite(window.resets_at)) return '未提供重置时间';
  try {
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(window.resets_at * 1000)) + ' 北京时间';
  } catch { return '未提供重置时间'; }
}
function translateError(text) {
  if (!text) return '';
  if (/login expired|unauthorized|rejected; sign in/i.test(text)) return '登录已失效，请重新授权';
  if (/not signed in/i.test(text)) return '尚未授权';
  if (/mismatch|different account/i.test(text)) return '账号身份不匹配，请重新授权';
  if (/network|proxy|timed out/i.test(text)) return '网络连接失败，请检查代理 / SSH 隧道';
  if (/Another CX window/i.test(text)) return '另一个窗口正在查询或授权，请稍后重试';
  return text;
}
function summary(account) {
  if (account.error) return translateError(account.error);
  if (account.quota) return `5h ${remaining(account.quota.five_hour)} · 周 ${remaining(account.quota.weekly)}`;
  return account.saved ? '已保存登录 · 尚未查询额度' : '尚未授权';
}
function mergeSnapshot(previous, fresh) {
  // Preserve the original query time; a cheap file scan is not a live quota query.
  return { ...fresh, quotaUpdatedAt: previous?.quotaUpdatedAt,
    accounts: fresh.accounts.map(account => {
      const old = previous?.accounts.find(a => a.id === account.id && a.email === account.email);
      return account.saved && old ? { ...old, ...account } : account;
    }) };
}
module.exports = { remaining, reset, translateError, summary, mergeSnapshot };
