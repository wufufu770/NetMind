import test from 'node:test';
import assert from 'node:assert/strict';
import { applyAuthMode, readonlyWriteBlock, request } from './client.js';

// request() 会读 localStorage 取凭据；node 里没有，先装个空的。
// （client.test.js 里也各装各的——重复但无害，比跨文件共享状态好查。）
const _store = new Map();
globalThis.localStorage = {
  getItem: (k) => (_store.has(k) ? _store.get(k) : null),
  setItem: (k, v) => _store.set(k, String(v)),
  removeItem: (k) => _store.delete(k),
};

// 只读身份的写请求闸门。
//
// 此前只在「触发自愈」一个操作上做了按钮级守卫——全站 41 个写操作里
// **只有 1 个被拦**。诚实表却声称「面板提前告知，而不是让只读用户点进去
// 撞 403」：横幅会弹，但其余 40 个按钮照点不误，照样吃服务端 403。

test('只读身份：写方法被拦，读方法放行', () => {
  applyAuthMode('readonly-token');
  for (const m of ['POST', 'PUT', 'PATCH', 'DELETE', 'post', 'delete']) {
    const r = readonlyWriteBlock(m);
    assert.ok(r, `${m} 应当被拦`);
    assert.match(r, /只读身份/);
    assert.match(r, /未发往服务端/);
  }
  for (const m of ['GET', 'HEAD', 'OPTIONS', undefined]) {
    assert.equal(readonlyWriteBlock(m), null, `${m} 不该被拦`);
  }
});

test('管理员与未知身份：写方法放行', () => {
  applyAuthMode('token');
  assert.equal(readonlyWriteBlock('POST'), null);
  applyAuthMode('unknown');
  assert.equal(readonlyWriteBlock('POST'), null,
    '身份还没拿到时不该乱拦——那会把管理员也挡在外面');
});

test('request 在只读身份下不发网络请求', async () => {
  applyAuthMode('readonly-token');
  let called = 0;
  const origFetch = globalThis.fetch;
  globalThis.fetch = async () => { called += 1; throw new Error('不该到网络'); };
  try {
    await assert.rejects(() => request('/api/config/reset-runtime', { method: 'POST' }), (e) => {
      assert.equal(e.status, 'blocked-client-side');
      assert.equal(e.blockedClientSide, true);
      assert.match(e.message, /只读身份/);
      return true;
    });
    assert.equal(called, 0, '请求被发往服务端了');
  } finally {
    globalThis.fetch = origFetch;
  }
});

test('只读身份的读请求照常发出', async () => {
  applyAuthMode('readonly-token');
  const origFetch = globalThis.fetch;
  let called = 0;
  globalThis.fetch = async () => {
    called += 1;
    return { ok: true, status: 200, headers: { get: () => 'application/json' },
             json: async () => ({ ok: true }) };
  };
  try {
    const r = await request('/api/dashboard');
    assert.deepEqual(r, { ok: true });
    assert.equal(called, 1, '读请求不该被拦');
  } finally {
    globalThis.fetch = origFetch;
  }
});

test('闸门会随 authMode 变化而开关', async () => {
  const origFetch = globalThis.fetch;
  let called = 0;
  globalThis.fetch = async () => { called += 1; throw new Error('不该到网络'); };
  try {
    applyAuthMode('readonly-token');
    await assert.rejects(() => request('/api/x', { method: 'POST' }));
    applyAuthMode('token');
    await assert.rejects(() => request('/api/x', { method: 'POST' }), (e) => {
      // 管理员身份下应当**真的发出去**（fetch 桩会抛），而不是被客户端拦下
      assert.notEqual(e.blockedClientSide, true);
      assert.match(e.message, /不该到网络/);
      return true;
    });
    // 只读那次被客户端拦下、根本没到 fetch；管理员那次才真发出去。合计 1 次。
    assert.equal(called, 1, '管理员身份下请求应当真的发出去，而只读的应当一次都没发');
  } finally {
    globalThis.fetch = origFetch;
    applyAuthMode('unknown');
  }
});
