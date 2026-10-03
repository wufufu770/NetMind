/** 请求凭据与认证失败的处理。
 *
 * 此前这段逻辑埋在 `App.jsx` 的 `request()` 里（1859 行文件的第 174 行），
 * 发出的是 `X-NetMind-Admin` 自定义头——而后端只读 `Authorization: Bearer`。
 * 结果：按 `docs/DEPLOY.md` 第 1 节配了 `NETMIND_ADMIN_TOKEN` 之后，
 * **网页面板的每一个请求都是 401**，整个界面不可用。
 *
 * 还有一处更隐蔽的问题：原代码有个写死的兜底凭据
 * `'netmind-local-admin'`。后端不认它，所以只是个无效字符串；但如果哪天
 * 有人「顺手」让后端认了这个头，它就成了一份**所有人都知道的固定默认凭据**。
 * 现在没有任何默认凭据——没配就是没配。
 */

const ADMIN_KEY = 'netmind-admin-token';
const READONLY_KEY = 'netmind-readonly-token';

/** 从存储与构建期环境变量里取凭据。取不到就是空串，不兜底。 */
export function resolveToken(kind, storage, env) {
  const key = kind === 'readonly' ? READONLY_KEY : ADMIN_KEY;
  const envName = kind === 'readonly' ? 'VITE_READONLY_TOKEN' : 'VITE_ADMIN_TOKEN';
  const fromStorage = storage && storage.getItem ? storage.getItem(key) : null;
  return (fromStorage || (env && env[envName]) || '').trim();
}

/** 给请求加认证头。
 *
 * 只读凭据优先于管理员凭据：两者都配了的话，用只读的那份能验证面板确实
 * 按只读身份工作；需要写操作时页面会拿到 403，提示用户换管理员凭据。
 */
export function authHeaders(kind, storage, env) {
  const token = resolveToken(kind, storage, env);
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

/** 401/403 要说人话。
 *
 * 这两种状态对使用者的含义完全不同：401 是「你没给凭据或给错了」，
 * 403 是「凭据有效但这个角色没这个权限」。混成一句「请求失败」，
 * 使用者既不知道该配 token 还是该换角色，只能反复重试。
 */
export function describeAuthFailure(status, payload) {
  const detail = (payload && (payload.error || payload.detail)) || '';
  if (status === 401) {
    return '需要有效凭据。在浏览器控制台执行 '
      + `localStorage.setItem('${ADMIN_KEY}', '<你的 token>') `
      + '后刷新，或用只读凭据 localStorage.setItem(\''
      + `${READONLY_KEY}', '<你的只读 token>')` + '。';
  }
  if (status === 403) {
    return String(detail).includes('只读')
      ? '当前凭据是只读身份，这个操作需要管理员凭据。'
      : String(detail) || '凭据有效，但没有这个操作的权限。';
  }
  return String(detail);
}
