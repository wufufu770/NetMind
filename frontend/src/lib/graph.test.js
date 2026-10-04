import test from 'node:test';
import assert from 'node:assert/strict';
import { graphToText, textToGraph } from './graph.js';
import { layoutNodes, resolveEndpoints } from './topology.js';

// 这两处此前都是「静默出错」：坏输入被悄悄丢弃，结果看起来完全正常。
// 画布照常渲染，只是少了一条边、或者凭空多了一条边。

test('图 → 文本：数组与对象两种边格式都能序列化', () => {
  const a = graphToText({ nodes: ['a', 'b'], edges: [['a', 'b']] });
  assert.equal(a.nodesText, 'a\nb');
  assert.equal(a.edgesText, 'a -> b');

  const b = graphToText({ nodes: ['a', 'b'], edges: [{ source: 'a', target: 'b' }] });
  assert.equal(b.edgesText, 'a -> b');
});

test('图 → 文本 → 图 往返后结构不变', () => {
  const graph = { nodes: ['parse', 'verify', 'deploy'], edges: [['parse', 'verify'], ['verify', 'deploy']] };
  const text = graphToText(graph);
  const back = textToGraph(text.nodesText, text.edgesText);
  assert.deepEqual(back.nodes, graph.nodes);
  assert.deepEqual(back.edges, graph.edges);
  assert.deepEqual(back.problems, [], '往返不该产生任何问题');
});

test('三段式的边不再被悄悄吞掉', () => {
  // 旧实现：.filter((e) => e.length === 2) 把这条直接丢掉，用户什么提示都收不到
  const r = textToGraph('a\nb\nc', 'a -> b -> c');
  assert.equal(r.edges.length, 0, '三段式不该被当成一条边');
  assert.equal(r.problems.length, 1);
  assert.equal(r.problems[0].kind, 'malformed');
  assert.match(r.problems[0].message, /第 1 行/);
});

test('箭头方向写反会被自动纠正并告知', () => {
  // B <- A 用户想表达的就是 A -> B。能修的就该修，不该只报错让人自己找。
  const r = textToGraph('a\nb', 'b <- a');
  assert.deepEqual(r.edges, [['a', 'b']]);
  assert.equal(r.problems.length, 1);
  assert.equal(r.problems[0].kind, 'reversed');
  assert.equal(r.problems[0].fixed, true);
  assert.match(r.problems[0].message, /方向反了/);
});

test('指向不存在节点的边会被指出来', () => {
  // 结构上合法，图上却是一条连不到东西的线——此前毫无提示
  const r = textToGraph('a\nb', 'a -> ghost');
  assert.deepEqual(r.edges, [['a', 'ghost']], '边本身仍保留');
  assert.equal(r.problems.length, 1);
  assert.equal(r.problems[0].kind, 'unknown-endpoint');
  assert.match(r.problems[0].message, /ghost/);
});

test('空文本与 null 不炸', () => {
  for (const [n, e] of [['', ''], [null, undefined], [undefined, null]]) {
    const r = textToGraph(n, e);
    assert.deepEqual(r.nodes, []);
    assert.deepEqual(r.edges, []);
    assert.deepEqual(r.problems, []);
  }
});

test('布局：同名节点不互相覆盖', () => {
  // 旧实现 acc[id] = ... 会被后者覆盖，等于凭空少一台设备
  const { positions, collisions } = layoutNodes([{ id: 'r1' }, { id: 'r1' }]);
  assert.equal(collisions.length, 1);
  assert.match(collisions[0].message, /r1/);
  assert.notDeepEqual(positions['r1'], positions['r1#1'],
    '两台设备叠在同一坐标上，图看着有、其实少了一台');
});

test('布局：无 id 时回落到名字或序号', () => {
  const { positions } = layoutNodes([{ name: 'core' }, { id: 'edge' }, 'bare', null]);
  assert.ok(positions.core && positions.edge && positions.bare && positions['3']);
});

test('连线端点缺失时明确报 missing，而不是编一个坐标', () => {
  // 旧实现 || [10, 10] 会凭空画出一条边——画出来的拓扑在撒谎
  const { positions } = layoutNodes([{ id: 'a' }, { id: 'b' }]);
  const ok = resolveEndpoints({ src: 'a', dst: 'b' }, positions);
  assert.deepEqual(ok.missing, []);

  const bad = resolveEndpoints({ src: 'a', dst: 'ghost' }, positions);
  assert.deepEqual(bad.missing, ['ghost']);
  assert.equal(bad.dst, undefined, '端点缺失时不得回退到固定坐标');
});

test('连线端点兼容 source/target 与 from/to 两种字段名', () => {
  const { positions } = layoutNodes([{ id: 'a' }, { id: 'b' }]);
  for (const link of [{ src: 'a', dst: 'b' }, { source: 'a', target: 'b' },
    { from: 'a', to: 'b' }]) {
    assert.deepEqual(resolveEndpoints(link, positions).missing, [], JSON.stringify(link));
  }
});

// ---- key 解析一致性 ----
//
// 实测踩过：渲染端用 `node.id || node.name || \`node-${index}\`` 查坐标，
// 而 layoutNodes 对无 id 的节点存的是序号的**字符串**（`'3'`）。
// key 拼法两边不一致 → `positions[key]` 为 undefined →
// `const [x, y] = undefined` 在浏览器里抛 TypeError，页面白屏。
// 而 build 与模块自身测试**都是绿的**——它们都不碰调用点。
import { positionOf } from './topology.js';

test('positionOf：渲染方按下标取，不自己拼 key', () => {
  const m = layoutNodes([{ id: 'a' }, { name: 'core' }, 'bare', null]);
  // 四种节点形态都要画得出来——无 id 的节点布局存的是序号的**字符串**（'3'），
  // 渲染端若用 `node-${index}` 去查就得到 undefined，浏览器里直接白屏
  for (const i of [0, 1, 2, 3]) {
    assert.ok(positionOf(i, m), `第 ${i} 个节点取不到坐标`);
  }
});

test('positionOf：同名节点错开后各自取到不同坐标', () => {
  // 曾经的第二个 bug：改成「主键查不到再退化到冲突键」也不对——主键从不缺失
  //（它就是前一个同名节点的槽位），于是两台设备仍重叠，等于没修
  const l = layoutNodes([{ id: 'r1' }, { id: 'r1' }]);
  const a = positionOf(0, l);
  const b = positionOf(1, l);
  assert.ok(a && b);
  assert.notDeepEqual(a, b, '两台设备仍叠在同一坐标上');
});

test('positionOf：查不到时返回 null 而不是 undefined', () => {
  // undefined 会被 `const [x, y] = pos` 解构成 TypeError；null 至少能被显式判掉
  assert.equal(positionOf(99, layoutNodes([{ id: 'a' }])), null);
});
