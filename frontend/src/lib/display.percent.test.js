import test from 'node:test';
import assert from 'node:assert/strict';
import { percentText } from './display.js';

// 后端返回 null 是「没采到数据」，不是「丢包率是 0」。
// 面板上真实出现过这个矛盾：延迟显示 --，丢包却显示 0.00%。

test('缺失值显示占位符，不显示 0%', () => {
  assert.equal(percentText(null), '--');
  assert.equal(percentText(undefined), '--');
  assert.equal(percentText(''), '--');
  assert.equal(percentText(NaN), '--');
});

test('真实的 0 照实显示', () => {
  assert.equal(percentText(0), '0.00%');
});

test('正常换算', () => {
  assert.equal(percentText(0.018), '1.80%');
  assert.equal(percentText(1), '100.00%');
});
