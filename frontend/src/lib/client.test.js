import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeList, request } from './client.js';

// `request()` 承载认证契约，而那份契约被打错过两次：
//   ① 发过 `X-NetMind-Admin` 自定义头，而后端只读 `Authorization: Bearer`
//      ——配了 token 之后面板全线 401
//   ② 留过一个写死的默认凭据 'netmind-local-admin'
// 两次都因为它困在带 JSX 的入口文件里而**一行测试都写不了**，只能靠人眼。
// 抽到 lib/ 之后这些就能钉死了。

/** 装一套可控的 localStorage + fetch。 */
function harness({ status = 200, body = { ok: true }, tokens = {} } = {}) {
  const store = new Map(Object.entries(tokens));
  const calls = [];
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => 'application/json' },
      json: async () => body,
      text: async () => JSON.stringify(body),
    };
  };
  return { calls, store };
}

test('请求带 Authorization: Bearer，不自造头', async () => {
  const { calls } = harness({ tokens: { 'netmind-admin-token': 'adm' } });
  await request('/api/dashboard');
  const h = calls[0].init.headers;
  assert.equal(h.Authorization, 'Bearer adm');
  assert.equal(h['X-NetMind-Admin'], undefined, '又自造了一个后端不认的头');
});

test('没有默认凭据：取不到就是取不到', async () => {
  const { calls } = harness({ tokens: {} });
  await request('/api/dashboard');
  assert.equal(calls[0].init.headers.Authorization, undefined,
    '凭空多出了一个凭据——那是一份所有人都知道的固定口令');
});

test('只读凭据与管理员凭据是两份，取哪种由调用方指定', async () => {
  const { calls } = harness({
    tokens: { 'netmind-admin-token': 'adm', 'netmind-readonly-token': 'ro' } });
  await request('/api/dashboard');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer adm');
  await request('/api/dashboard', { credentialKind: 'readonly' });
  assert.equal(calls[1].init.headers.Authorization, 'Bearer ro');
});

test('credentialKind 是内部控制参数，不该漏进 fetch 的 init', async () => {
  const { calls } = harness({ tokens: { 'netmind-admin-token': 'adm' } });
  await request('/api/dashboard', { credentialKind: 'readonly' });
  assert.equal(calls[0].init.credentialKind, undefined,
    '把内部控制字段发到了请求上');
});

test('body 对象自动 JSON 化并带上 Content-Type', async () => {
  const { calls } = harness({ tokens: { 'netmind-admin-token': 'adm' } });
  await request('/api/intent/parse', { method: 'POST', body: { text: 'hi' } });
  assert.equal(calls[0].init.body, '{"text":"hi"}');
  assert.equal(calls[0].init.headers['Content-Type'], 'application/json');
});

test('body 是字符串时不再二次编码', async () => {
  const { calls } = harness({ tokens: { 'netmind-admin-token': 'adm' } });
  await request('/api/x', { method: 'POST', body: '{"already":"json"}' });
  assert.equal(calls[0].init.body, '{"already":"json"}');
});

test('401 与 403 抛出可区分的错误', async () => {
  // 401 = 没给或给错凭据；403 = 凭据有效但角色不够。混成一句使用者只能反复重试。
  harness({ status: 401, tokens: { 'netmind-admin-token': 'bad' } });
  await assert.rejects(() => request('/api/dashboard'), (e) => {
    assert.equal(e.status, 401);
    assert.match(e.message, /netmind-admin-token/);
    return true;
  });

  // 403 的响应体按后端真实形状伪造：文案取自 backend/app/core/access.py 的
  // 只读分支（'只读凭据不得执行写操作。读接口（GET/HEAD/OPTIONS）不受限；…'）。
  // 用不真实的 body 测，测的是 mock 而不是契约。
  harness({
    status: 403,
    body: {
      error: '只读凭据不得执行写操作。读接口（GET/HEAD/OPTIONS）不受限；'
        + '需要下发或变更请改用 NETMIND_ADMIN_TOKEN',
      auth_mode: 'readonly-token',
    },
    tokens: { 'netmind-readonly-token': 'ro' },
  });
  await assert.rejects(() => request('/api/telemetry/heal', { method: 'POST' }),
    (e) => {
      assert.equal(e.status, 403);
      // 契约是「提示能区分角色问题」，不是逐字透传后端文案：
      // describeAuthFailure 识别出只读后会用更友好的措辞替掉原文。
      assert.match(e.message, /只读身份/);
      assert.ok(!e.message.includes('需要有效的 Bearer token'),
        '403 不该被说成「凭据无效」，否则使用者会去无谓地换凭据');
      return true;
    });
});

test('非认证失败原样透出后端信息', async () => {
  harness({ status: 500, body: { detail: 'boom' }, tokens: { 'netmind-admin-token': 'a' } });
  await assert.rejects(() => request('/api/x'), /boom/);
});

test('normalizeList 覆盖后端几种返回形状', () => {
  assert.deepEqual(normalizeList(null), []);
  assert.deepEqual(normalizeList(undefined), []);
  assert.deepEqual(normalizeList([1, 2]), [1, 2]);
  assert.deepEqual(normalizeList({ items: [3] }), [3]);
  assert.deepEqual(normalizeList({ a: 1, b: 2 }), [1, 2]);
  assert.deepEqual(normalizeList('x'), []);
});
