import test from 'node:test';
import assert from 'node:assert/strict';
import { authHeaders, describeAuthFailure, resolveToken } from './auth.js';

const store = (obj) => ({ getItem: (k) => (k in obj ? obj[k] : null) });

test('凭据用 Authorization: Bearer 发送，不自造头', () => {
  const h = authHeaders('admin', store({ 'netmind-admin-token': 'abc' }), {});
  assert.equal(h.Authorization, 'Bearer abc');
  // 这条是本文件存在的全部理由：此前发的是 X-NetMind-Admin，
  // 而后端只读 authorization，于是配了 token 之后面板全线 401
  assert.equal(h['X-NetMind-Admin'], undefined);
});

test('没有任何默认凭据', () => {
  assert.deepEqual(authHeaders('admin', store({}), {}), {});
  assert.deepEqual(authHeaders('readonly', store({}), {}), {});
  // 写死的 'netmind-local-admin' 那类兜底，离「一份所有人都知道的固定凭据」
  // 只差后端认不认那个头
  assert.equal(resolveToken('admin', store({}), {}), '');
});

test('存储优先于构建期环境变量', () => {
  assert.equal(
    resolveToken('admin', store({ 'netmind-admin-token': 'from-store' }),
      { VITE_ADMIN_TOKEN: 'from-env' }),
    'from-store');
  assert.equal(
    resolveToken('admin', store({}), { VITE_ADMIN_TOKEN: 'from-env' }), 'from-env');
});

test('只读与管理员是两份独立凭据', () => {
  const s = store({ 'netmind-admin-token': 'adm', 'netmind-readonly-token': 'ro' });
  assert.equal(authHeaders('admin', s, {}).Authorization, 'Bearer adm');
  assert.equal(authHeaders('readonly', s, {}).Authorization, 'Bearer ro');
});

test('空白凭据等同没配', () => {
  assert.deepEqual(
    authHeaders('admin', store({ 'netmind-admin-token': '   ' }), {}), {});
});

test('401 与 403 的提示不能混', () => {
  const unauth = describeAuthFailure(401, { error: '需要有效的 Bearer token' });
  const forbidden = describeAuthFailure(403, { error: '只读凭据不得执行写操作' });
  assert.match(unauth, /netmind-admin-token/);
  assert.ok(!unauth.includes('只读身份'), '401 不该说成权限问题——那是 403 的含义');

  assert.match(forbidden, /只读身份/);
  assert.ok(!forbidden.includes('需要有效凭据'), '403 是凭据有效但角色不够，不该让用户去换凭据');
});

test('非认证失败原样透传', () => {
  assert.equal(describeAuthFailure(500, { detail: 'boom' }), 'boom');
  assert.equal(describeAuthFailure(404, null), '');
});

test('存储不可用时不抛异常', () => {
  assert.deepEqual(authHeaders('admin', null, null), {});
  assert.deepEqual(authHeaders('admin', {}, {}), {});
});
