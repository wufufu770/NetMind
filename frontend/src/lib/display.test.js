import test from 'node:test';
import assert from 'node:assert/strict';
import {
  confidenceText, healthRing, healthScore, metricTone, metricValue, summaryCell,
} from './display.js';

// 算不出来就显示「没有」，不拿一个像样的数字占位。
// 这组用例锁的是「用户被告知什么」——错了就是又一次谎报。

test('缺失值显示占位符，不显示 0', () => {
  assert.equal(metricValue(null), '--');
  assert.equal(metricValue(undefined), '--');
  assert.equal(metricValue(''), '--');
  assert.equal(metricValue(NaN), '--');
  assert.equal(metricValue(Infinity), '--');
  assert.equal(metricValue(0), 0, '0 是测出来的零，必须照实显示');
});

test('健康分算不出来就是 null，不得按丢包率反推', () => {
  assert.equal(healthScore(null), null);
  assert.equal(healthScore(undefined), null);
  assert.equal(healthScore(''), null);
  assert.equal(healthScore('abc'), null);
  // 早前的写法：sla 为空时用 packet_loss 推出 96/82
  assert.notEqual(healthScore(null), 96);
  assert.notEqual(healthScore(null), 82);
});

test('健康分超界时夹到 0–100', () => {
  assert.equal(healthScore(0), 0);
  assert.equal(healthScore(99.6), 99.6);
  assert.equal(healthScore(140), 100);
  assert.equal(healthScore(-5), 0);
});

test('健康环画空环但文字仍是占位符', () => {
  const missing = healthRing(null);
  assert.equal(missing.drawn, 0, '画 0 环');
  assert.equal(missing.label, '--', '但文字不能是 0——那是把「没测」说成「测了 0 分」');
  assert.deepEqual(healthRing(96), { drawn: 96, label: 96 });
});

test('无数据时色调为中性，不用 ok', () => {
  assert.equal(metricTone(null, { warnAbove: 50 }), 'neutral');
  assert.equal(metricTone(undefined, { warnAbove: 50 }), 'neutral');
  assert.equal(metricTone('x', { warnAbove: 50 }), 'neutral');
});

test('有数据时按阈值定色', () => {
  const t = { warnAbove: 50, badAbove: 200 };
  assert.equal(metricTone(10, t), 'ok');
  assert.equal(metricTone(60, t), 'warn');
  assert.equal(metricTone(250, t), 'bad');
});

test('未提供的判断显示「未知」，不猜', () => {
  const c = summaryCell(undefined, { yes: '可行', no: '不可行' });
  assert.equal(c.text, '未知');
  assert.equal(c.tone, 'neutral', '未知不该染成成功色');
});

test('已提供的判断照实显示', () => {
  assert.deepEqual(summaryCell(true, { yes: '可行', no: '不可行' }),
    { text: '可行', tone: 'ok' });
  assert.deepEqual(summaryCell(false, { yes: '可行', no: '不可行' }),
    { text: '不可行', tone: 'warn' });
});

test('未提供与「否」是两回事', () => {
  // 早前 sla_feasible 恒为 true，于是「后端没给判断」被显示成「可行 100%」
  const unknown = summaryCell(undefined, { yes: '可行', no: '不可行' });
  const no = summaryCell(false, { yes: '可行', no: '不可行' });
  assert.notEqual(unknown.text, no.text);
});

test('置信度缺失时显示占位符，不显示 0%', () => {
  assert.equal(confidenceText(null), '—');
  assert.equal(confidenceText(undefined), '—');
  assert.equal(confidenceText(0), '0%', '真的 0 置信度要照实显示');
  assert.equal(confidenceText(0.394), '39%');
  assert.equal(confidenceText(1), '100%');
});
