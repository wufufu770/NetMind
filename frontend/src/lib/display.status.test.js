import test from 'node:test';
import assert from 'node:assert/strict';
import { netStatusLabel } from './display.js';

// 「全网正常」是整块界面上最要紧的一句话。此前它在任何检查都没跑过时
// 就显示绿色对勾 + 「正常」——health 初始为 null，`health?.alerts` 为
// undefined，于是走进 else 分支。紧挨着的模型那行本来就是三态，这里补齐。

test('没跑过检查时不说「正常」', () => {
  assert.equal(netStatusLabel(null), '未检查');
  assert.equal(netStatusLabel(undefined), '未检查');
});

test('拿到了响应但没有可判的告警数，也不当成「正常」', () => {
  assert.equal(netStatusLabel({}), '未检查');
  assert.equal(netStatusLabel({ alerts: null }), '未检查');
  assert.equal(netStatusLabel({ alerts: 'x' }), '未检查');
});

test('有真实告警数时照实显示', () => {
  assert.equal(netStatusLabel({ alerts: 3 }), '3 告警');
  assert.equal(netStatusLabel({ alerts: 1 }), '1 告警');
});

test('告警数为 0 时才说「正常」', () => {
  assert.equal(netStatusLabel({ alerts: 0 }), '正常');
  assert.notEqual(netStatusLabel({ alerts: 0 }), '未检查');
});
