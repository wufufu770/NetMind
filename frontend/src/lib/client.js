/** 前端与后端之间的那一层：请求、凭据、几个通用副作用。
 *
 * 从 App.jsx（1887 行）抽出来的零 JSX 段。抽它的理由不是「文件太长」——
 * 是**这段此前一行测试都写不了**：`node --test` 只能直接 import 纯模块，
 * 而 App.jsx 是带 JSX 的入口文件。而 `request()` 恰好承载认证契约，
 * 那份契约已经被打错过两次（发过 X-NetMind-Admin、留过写死的默认凭据）。
 * 能测之前，它只是「看起来对」。
 *
 * 依赖注入的边界：localStorage / import.meta.env / fetch 都从参数或全局取，
 * 便于测试时替换——见 client.test.js。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl, resolveApiBase } from './api.js';
import { authHeaders, describeAuthFailure } from './auth.js';

/** API 基址。同源优先，见 api.js 的说明。 */
export const API = resolveApiBase(
  typeof window === 'undefined' ? null : window,
  typeof import.meta === 'undefined' ? {} : import.meta.env);

function normalizeList(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.items)) return data.items;
  if (typeof data === 'object') return Object.values(data);
  return [];
}

async function request(path, options = {}) {
  // 只读身份的发写请求在**浏览器侧**就拦下，不发往服务端
  const _blocked = readonlyWriteBlock(options.method);
  if (_blocked) {
    const _e = new Error(_blocked);
    _e.status = 'blocked-client-side';
    _e.blockedClientSide = true;
    throw _e;
  }
  const headers = { ...(options.headers || {}) };
  // 认证走 `Authorization: Bearer`——后端只认这个。此前发的是 `X-NetMind-Admin`
  // 自定义头，后端根本不读，于是配了 NETMIND_ADMIN_TOKEN 之后面板全线 401。
  // 也没有默认凭据：原来那个写死的 'netmind-local-admin' 只是一串无效字符串，
  // 但它离「一份所有人都知道的固定凭据」只差后端认不认这个头。
  const kind = options.credentialKind || 'admin';
  Object.assign(headers, authHeaders(kind, localStorage, import.meta.env));
  delete options.credentialKind;
  const init = { ...options, headers };
  if (init.body && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body);
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }
  const res = await fetch(apiUrl(path, API), init);
  const contentType = res.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      const err = new Error(describeAuthFailure(res.status, payload));
      err.status = res.status;
      throw err;
    }
    const message = typeof payload === 'string' ? payload : payload.detail || JSON.stringify(payload);
    throw new Error(message);
  }
  return payload;
}

function useApi(path, initial = null, refreshKey = 0) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState('');
  const reload = async () => {
    if (!path) return;
    setLoading(true);
    setError('');
    try {
      setData(await request(path));
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    reload();
  }, [path, refreshKey]);
  return { data, setData, loading, error, reload };
}

function useLocalSettings() {
  const [settings, setSettings] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('netmind-ui-settings')) || {};
    } catch {
      return {};
    }
  });
  const merged = {
    theme: settings.theme || 'aurora',
    font: settings.font || 'system',
    fontSize: settings.fontSize || 1,
    density: settings.density || 'comfortable',
    ...settings,
  };
  useEffect(() => {
    localStorage.setItem('netmind-ui-settings', JSON.stringify(merged));
    const preset = themePresets[merged.theme] || themePresets.aurora;
    const font = fontChoices.find((f) => f.id === merged.font) || fontChoices[0];
    const root = document.documentElement;
    Object.entries(preset).forEach(([key, value]) => {
      if (key !== 'name') root.style.setProperty(`--${key}`, value);
    });
    root.style.setProperty('--font-family', font.family);
    root.style.setProperty('--font-scale', String(merged.fontSize));
    root.dataset.density = merged.density;
  }, [merged.theme, merged.font, merged.fontSize, merged.density]);
  return [merged, (patch) => setSettings((prev) => ({ ...prev, ...patch }))];
}

function toastMessage(setToast, type, text) {
  setToast({ type, text, id: Date.now() });
}

function copyText(text, setToast) {
  const value = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  navigator.clipboard?.writeText(value || '').then(
    () => toastMessage(setToast, 'success', '已复制到剪贴板'),
    () => toastMessage(setToast, 'warn', '浏览器不允许复制，请手动选择内容')
  );
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export { normalizeList };
export { request };
export { useApi };
export { useLocalSettings };
export { toastMessage };
export { copyText };
export { downloadText };

/** 只读身份的写请求闸门。
 *
 * 此前只在「触发自愈」一个操作上做了按钮级守卫——全站 41 个写操作里
 * **只有 1 个被拦**。诚实表声称「面板提前告知，而不是让只读用户点进去撞 403」，
 * 实际是：横幅会弹，但其余 40 个按钮照点不误，照样吃服务端 403。
 *
 * 拦在这里（而不是 41 处各写一遍）有两个理由：
 *   ① 41 处一定会漏——漏一处就等于承诺不成立，新增操作时同样会漏
 *   ② 「只读身份不许写」是**一条规则**，不是某个按钮的属性
 * 将来新增任何写操作都自动被覆盖，不需要记得加守卫。
 */
let _authMode = 'unknown';

export function applyAuthMode(mode) {
  _authMode = String(mode || 'unknown');
}

export function clientAuthMode() {
  return _authMode;
}

const WRITE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE'];

/** 只读身份 + 写方法 ⇒ 不该发出去。返回字符串表示拒绝理由，null 表示放行。 */
export function readonlyWriteBlock(method) {
  if (_authMode !== 'readonly-token') return null;
  const m = String(method || 'GET').toUpperCase();
  if (!WRITE_METHODS.includes(m)) return null;
  return `当前是只读身份（auth_mode=${_authMode}），${m} 请求已在浏览器侧拦下，未发往服务端。`
    + '读操作不受限；下发与变更类操作需要管理员凭据（NETMIND_ADMIN_TOKEN）。';
}
