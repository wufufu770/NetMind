// 前端此前零测试——package.json 里连 test 脚本都没有，CI 只 build 不 test。
// 用 node 内置 test runner，不引任何依赖（承「零依赖」取向）。
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  compactLabel, displayToolName, executionLabel, localizeJsonText, TOOL_ALIASES,
} from './format.js';

test('compactLabel: 空值回落为占位符', () => {
  assert.equal(compactLabel(undefined), '--');
  assert.equal(compactLabel(null), '--');
  assert.equal(compactLabel(''), '--');
});

test('compactLabel: 去掉 free_ 前缀并把下划线转空格', () => {
  // 默认上限 12：'latency probe' 13 字符会被截断，这里显式放宽上限看完整形态
  assert.equal(compactLabel('free_latency_probe', 20), 'latency probe');
  assert.equal(compactLabel('a_b-c_d'), 'a b c d');
  // 默认上限下的实际行为
  assert.equal(compactLabel('free_latency_probe'), 'latency pro…');
});

test('compactLabel: 超长截断并加省略号', () => {
  const out = compactLabel('abcdefghijklmnop', 10);
  assert.equal(out.length, 10);
  assert.ok(out.endsWith('…'));
});

test('compactLabel: 恰好等于上限时不截断', () => {
  assert.equal(compactLabel('abcdefghij', 10), 'abcdefghij');
});

test('displayToolName: 命中别名表走中文名', () => {
  assert.equal(displayToolName('free_latency_probe'), '内置延迟探测');
  assert.equal(displayToolName('free_rollback_preview'), '内置回滚预览');
});

test('displayToolName: 未命中别名则去前缀并转空格', () => {
  assert.equal(displayToolName('free_custom_thing'), 'builtin custom thing');
  assert.equal(displayToolName('already_plain'), 'already plain');
});

test('displayToolName: 别名表每个条目都非空且唯一', () => {
  const vals = Object.values(TOOL_ALIASES);
  assert.ok(vals.length >= 13, `别名表条目偏少: ${vals.length}`);
  for (const v of vals) assert.ok(v && v.trim().length > 0, '存在空别名');
  assert.equal(new Set(vals).size, vals.length, '别名重复');
});

test('displayToolName: 空输入不炸', () => {
  assert.equal(displayToolName(undefined), '');
  assert.equal(displayToolName(null), '');
});

test('executionLabel: 优先级为 business > status > 兜底', () => {
  assert.equal(executionLabel({ intent: { business: 'video_meeting' }, status: 'done' }), 'video_meeting');
  assert.equal(executionLabel({ status: 'warning' }), 'warning');
  assert.equal(executionLabel({}), '执行记录');
  assert.equal(executionLabel(null), '未选择');
});

test('localizeJsonText: 模式与错误码转中文', () => {
  assert.ok(localizeJsonText('mode=dry_run').includes('试运行模式'));
  assert.ok(localizeJsonText('PATH_UNREACHABLE').includes('路径不可达'));
  assert.ok(localizeJsonText('SLA_RISK').includes('SLA 风险'));
});

test('localizeJsonText: 动态 id 不泄漏具体标识', () => {
  const out = localizeJsonText('intent-a1b2c3 exec-9f8e7d');
  assert.ok(!out.includes('a1b2c3'), '意图 id 未被脱敏');
  assert.ok(!out.includes('9f8e7d'), '执行 id 未被脱敏');
});

test('localizeJsonText: free_ 前缀处理顺序不产生 free_builtin 残留', () => {
  const out = localizeJsonText('free_builtin_thing');
  assert.ok(!out.includes('free_builtin'), `仍有 free_builtin 残留: ${out}`);
});
