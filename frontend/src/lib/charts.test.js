import test from 'node:test';
import assert from 'node:assert/strict';
import { filterByKeyword, matchesKeyword, sparklinePoints } from './charts.js';

// 测不到的延迟被当成 0 画进图里，看起来是个好消息——比缺测更坏。
// 遥测字段改成可缺之后（latency_ms 可能是 null），这条路更是直接被打开。

test('缺测的点不画，不用 0 顶替', () => {
  const r = sparklinePoints(
    [{ latency_ms: 10 }, { latency_ms: null }, { latency_ms: 30 }], 'latency_ms');
  assert.equal(r.drawn, 2, '只有两个测到的点');
  assert.equal(r.dropped, 1);
  assert.equal(r.points.split(' ').length, 2);
  assert.ok(!r.points.includes('NaN'));
});

test('全部缺测时返回空并标记 empty，不画一条空折线', () => {
  const r = sparklinePoints([{ latency_ms: null }, { latency_ms: undefined }], 'latency_ms');
  assert.equal(r.points, '');
  assert.equal(r.empty, true);
  assert.equal(r.drawn, 0);
  assert.equal(r.dropped, 2);
});

test('空数组不炸', () => {
  for (const input of [[], null, undefined]) {
    const r = sparklinePoints(input, 'latency_ms');
    assert.equal(r.empty, true);
    assert.equal(r.points, '');
  }
});

test('非数值字段不产生 NaN——一个坏行不该毁掉整张图', () => {
  // 原实现 Number('abc') → NaN，NaN 进 points 属性，整条 polyline 不渲染
  const r = sparklinePoints(
    [{ v: 10 }, { v: 'abc' }, { v: {} }, { v: 30 }], 'v');
  assert.ok(!r.points.includes('NaN'), `points 里出现 NaN: ${r.points}`);
  assert.equal(r.drawn, 2);
  assert.equal(r.dropped, 2);
});

test('空串视为缺测而不是 0', () => {
  const r = sparklinePoints([{ v: '' }, { v: 5 }], 'v');
  assert.equal(r.drawn, 1);
  assert.equal(r.dropped, 1);
});

test('数值字符串照常取用（后端可能给字符串形态）', () => {
  const r = sparklinePoints([{ v: '10' }, { v: 20 }], 'v');
  assert.equal(r.drawn, 2);
  assert.equal(r.dropped, 0);
});

test('所有值相等时不除零', () => {
  const r = sparklinePoints([{ v: 7 }, { v: 7 }, { v: 7 }], 'v');
  assert.equal(r.drawn, 3);
  for (const pt of r.points.split(' ')) {
    const [, y] = pt.split(',').map(Number);
    assert.ok(Number.isFinite(y), `y 坐标不是有限数: ${pt}`);
  }
});

test('负值被夹在视口内，不会画到 viewBox 外面', () => {
  const r = sparklinePoints([{ v: -50 }, { v: 10 }], 'v');
  for (const pt of r.points.split(' ')) {
    const y = Number(pt.split(',')[1]);
    assert.ok(y >= 0 && y <= 100, `y=${y} 跑出视口`);
  }
});

test('丢点后线仍连续（按有效点排布而非原始下标）', () => {
  const r = sparklinePoints([{ v: null }, { v: 5 }, { v: null }, { v: 9 }], 'v');
  const xs = r.points.split(' ').map(p => Number(p.split(',')[0]));
  assert.equal(xs[0], 0);
  assert.equal(xs[xs.length - 1], 100, '有效点应铺满整个宽度');
});

test('空关键词返回全部，不是「匹配空串」的特例', () => {
  const rows = [{ m: 'a' }, { m: 'b' }];
  for (const q of ['', '   ', null, undefined]) {
    assert.equal(filterByKeyword(rows, q).length, 2, `关键词 ${JSON.stringify(q)}`);
  }
});

test('关键词过滤不区分大小写且跨字段', () => {
  const rows = [{ msg: 'Timeout on R1' }, { msg: 'ok' }, { id: 'ALPHA' }];
  const f = (q) => filterByKeyword(rows, q);
  assert.equal(f('timeout').length, 1);
  assert.equal(f('R1').length, 1);
  assert.equal(f('alpha').length, 1);
  assert.equal(f('ALPHA').length, 1, '大小写应当不敏感');
  assert.equal(f('nope').length, 0);
});

test('matchesKeyword 对 null 行不炸', () => {
  assert.equal(matchesKeyword(null, 'x'), false);
  assert.equal(matchesKeyword(null, ''), true);
});

test('相近但不同的值必须渲染成不同的 y', () => {
  // 第一版把值域直接算出的 y 再 clamp 到 [14, 100]，于是 12.4 与 11.8
  // （算出 0 和 4.16，都在视口内）被一起压成 14 —— 图看起来「没变化」。
  // **clamp 是越界的安全网，不该毁掉带子内的有效数据。**
  const r = sparklinePoints([{ v: 12.4 }, { v: 11.8 }], 'v');
  const ys = r.points.split(' ').map(p => Number(p.split(',')[1]));
  assert.equal(ys.length, 2);
  assert.notEqual(ys[0], ys[1], `两个不同的值渲染成同一个 y=${ys[0]}，变化被压平了`);
});

test('值域铺在留白带子内，不贴边也不越界', () => {
  const r = sparklinePoints([{ v: 0 }, { v: 50 }, { v: 100 }], 'v');
  for (const pt of r.points.split(' ')) {
    const y = Number(pt.split(',')[1]);
    assert.ok(y >= 0 && y <= 100, `y=${y} 越界`);
    assert.ok(y >= 14 - 0.01 && y <= 86 + 0.01, `y=${y} 没有落在留白带 [14,86] 内`);
  }
});
