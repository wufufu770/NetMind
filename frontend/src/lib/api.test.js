import test from 'node:test';
import assert from 'node:assert/strict';
import { apiUrl, resolveApiBase, wsUrl } from './api.js';

// 同源是默认且正确的选择：没有 CORS、没有预检、凭据不跨域。
// 此前这里写死 `VITE_API_URL || 'http://localhost:8000'`，构建期烤死，
// 且默认指向访问者本机——生产静态托管时会默默去打错的地方。

test('默认走同源，而不是访问者的 localhost', () => {
  assert.equal(resolveApiBase(undefined, {}), '');
  assert.equal(resolveApiBase({}, {}), '');
});

test('运行时注入优先于构建期变量', () => {
  assert.equal(resolveApiBase({ __NETMIND_API__: 'https://a.example' },
    { VITE_API_URL: 'https://b.example' }), 'https://a.example');
});

test('构建期变量次之', () => {
  assert.equal(resolveApiBase({}, { VITE_API_URL: 'https://b.example' }),
    'https://b.example');
});

test('结尾斜杠被去掉，避免拼出 //api', () => {
  assert.equal(resolveApiBase({ __NETMIND_API__: 'https://a.example/' }, {}),
    'https://a.example');
  assert.equal(apiUrl('/api/dashboard', 'https://a.example/'),
    'https://a.example/api/dashboard');
});

test('空串与空白视为未设置', () => {
  assert.equal(resolveApiBase({ __NETMIND_API__: '   ' },
    { VITE_API_URL: 'https://b.example' }), 'https://b.example');
});

test('拼接：同源时是根相对路径', () => {
  assert.equal(apiUrl('/api/dashboard', ''), '/api/dashboard');
  assert.equal(apiUrl('api/dashboard', ''), '/api/dashboard');
  assert.equal(apiUrl('/api/dashboard', 'https://a.example'),
    'https://a.example/api/dashboard');
});

test('WebSocket 由 http 推导 ws', () => {
  assert.equal(wsUrl('/ws/events', 'http://a.example'), 'ws://a.example/ws/events');
  assert.equal(wsUrl('/ws/events', 'https://a.example'), 'wss://a.example/ws/events');
});

test('同源且页面为 https 时必须走 wss，否则浏览器按混合内容拒掉', () => {
  const saved = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'panel.example' };
  try {
    assert.equal(wsUrl('/ws/events', ''), 'wss://panel.example/ws/events');
  } finally {
    globalThis.location = saved;
  }
});

test('同源且页面为 http 时保持相对路径', () => {
  const saved = globalThis.location;
  globalThis.location = { protocol: 'http:', host: 'localhost:5173' };
  try {
    assert.equal(wsUrl('/ws/events', ''), '/ws/events');
  } finally {
    globalThis.location = saved;
  }
});
