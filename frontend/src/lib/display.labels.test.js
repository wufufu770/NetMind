import test from 'node:test';
import assert from 'node:assert/strict';
import { deviceStateLabel, provenanceLabel, timeLabel } from './display.js';

// 这三处此前在 UI 上对「没数据」给出了具体的断言：
// 设备「可用」、来源「system」、时间「刚刚」。都是凭空的，且都是关于
// 网络状态或数据可信度的事实——最不该编的三类。

test('设备既无 IP 也无状态时不说「可用」', () => {
  assert.equal(deviceStateLabel({ id: 'r1' }), '状态未知');
  assert.equal(deviceStateLabel({}), '状态未知');
  assert.equal(deviceStateLabel(null), '状态未知');
  assert.ok(!deviceStateLabel({ id: 'r1' }).includes('可用'),
    '没有任何数据说过这台设备可用');
});

test('设备有 IP 或状态时照实显示', () => {
  assert.equal(deviceStateLabel({ ip: '10.0.0.1' }), '10.0.0.1');
  assert.equal(deviceStateLabel({ status: 'down' }), 'down');
  assert.equal(deviceStateLabel({ ip: '', status: 'degraded' }), 'degraded');
});

test('来源缺失时说「来源未标注」，不替它编一个 system', () => {
  assert.equal(provenanceLabel({ ts: 'x' }), '来源未标注');
  assert.equal(provenanceLabel({}), '来源未标注');
  assert.ok(!provenanceLabel({}).includes('system'),
    '把「未知来源」说成 system 会抵消后端的来源标注');
});

test('来源存在时照实显示', () => {
  assert.equal(provenanceLabel({ source: 'simulated' }), 'simulated');
  assert.equal(provenanceLabel({ src: 'real' }), 'real');
});

test('没有时间戳的不说「刚刚」', () => {
  assert.equal(timeLabel({ source: 'x' }), '时间未标注');
  assert.equal(timeLabel({}), '时间未标注');
  assert.equal(timeLabel({ ts: 'not-a-date' }), '时间未标注',
    '解析不出来的日期也不能当成「刚刚」');
});

test('有合法时间戳时格式化输出', () => {
  const s = timeLabel({ ts: '2026-10-04T12:00:00Z' }, 'en-US');
  assert.ok(s && s !== '时间未标注');
  assert.match(s, /2026/);
});
