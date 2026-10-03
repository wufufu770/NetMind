/** API 基址解析。
 *
 * 此前是 `import.meta.env.VITE_API_URL || 'http://localhost:8000'`——
 * 构建期烤死，且默认指向 localhost。这有三个问题：
 *
 *   1. **同源不了**。跨源发 `Authorization` 头会触发 CORS 预检，
 *      而预检失败的表现常常是「看着像网络问题」，很难查。
 *   2. **烤死**。同一份镜像换个部署地址就得重新构建；
 *      compose 里写 `VITE_API_URL=http://localhost:8000` 对「用别人的浏览器
 *      访问你这台机器」的场景也是错的——那个 localhost 指的是访问者自己。
 *   3. **默认 localhost**。生产静态托管时若没注入，页面会默默去打
 *      访问者本机的 8000 端口。
 *
 * 现在优先用运行时注入的 `window.__NETMIND_API__`（nginx 启动时写进
 * index.html），其次构建期变量，最后**同源相对路径**——同源是默认且正确的
 * 选择：没有 CORS，没有预检，cookie/凭据不跨域。
 */

/** 从运行时全局、构建期变量里依次取基址；都没有就用同源（空串）。 */
export function resolveApiBase(runtime, env) {
  const injected = runtime && typeof runtime.__NETMIND_API__ === 'string'
    ? runtime.__NETMIND_API__.trim()
    : '';
  if (injected) return stripTrailing(injected);
  const fromEnv = env && env.VITE_API_URL ? String(env.VITE_API_URL).trim() : '';
  if (fromEnv) return stripTrailing(fromEnv);
  return '';
}

function stripTrailing(u) {
  return u.replace(/\/+$/, '');
}

/** 拼完整请求地址。同源时返回 `/api/...`，前端与后端同源无需 CORS。 */
export function apiUrl(path, base) {
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${stripTrailing(base ?? '')}${p}`;
}

/** WebSocket 地址。由 http(s) 推导 ws(s)，同源则直接用同源。 */
export function wsUrl(path, base) {
  const full = apiUrl(path, base);
  if (/^https?:\/\//i.test(full)) return full.replace(/^http/i, 'ws');
  // 页面若是 https，WebSocket 必须走 wss，否则浏览器直接拒（混合内容）
  if (typeof location !== 'undefined' && location.protocol === 'https:') {
    return `wss://${location.host}${full}`;
  }
  return full;
}
