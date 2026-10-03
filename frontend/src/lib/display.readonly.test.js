import test from 'node:test';
import assert from 'node:assert/strict';
import { isReadonly, writeAction } from './display.js';

test('只读身份被识别', () => {
  assert.equal(isReadonly('readonly-token'), true);
  assert.equal(isReadonly('token'), false);
  assert.equal(isReadonly('loopback-only'), false);
  assert.equal(isReadonly('public'), false);
  assert.equal(isReadonly(undefined), false);
});

test('只读身份下写操作被禁用并说明原因', () => {
  const a = writeAction('readonly-token', '下发策略');
  assert.equal(a.disabled, true);
  assert.match(a.title, /只读/);
  assert.match(a.title, /管理员凭据/);
});

test('管理员与本机不受影响', () => {
  assert.deepEqual(writeAction('token'), { disabled: false, title: '' });
  assert.deepEqual(writeAction('loopback-only'), { disabled: false, title: '' });
});

test('身份未知时不误伤——宁可让服务端返回 403', () => {
  // 猜测身份并禁用按钮，可能把本来能用的管理员也挡在门外
  assert.equal(writeAction(undefined).disabled, false);
  assert.equal(writeAction('unknown').disabled, false);
});
