/** 拓扑布局与连线端点解析。
 *
 * 原实现里两处静默出错：
 *   · 布局用 `acc[node.id || node.name || index] = ...`，两个节点同 id 时后者
 *     直接覆盖前者，两台设备叠在同一个坐标上，图看着「有」，其实少了一台
 *   · 连线端点找不到时 `|| [10, 10]` 静默落到固定坐标——**画出来的拓扑在撒谎**，
 *     凭空画出一条边，而数据里根本没有这个关系
 *
 * 这里把两处都改成显式报告：布局去重并回报冲突，连线端点解析不出就标记
 * `missing`，由 UI 决定是提示还是跳过，而不是编一个坐标出来。
 */

const DEFAULTS = [
  [50, 12], [18, 36], [82, 36], [18, 68], [50, 86],
  [82, 68], [50, 48], [8, 52], [92, 52],
];

export function layoutNodes(nodes) {
  const positions = {};
  const coords = [];          // 与 nodes **同序**——渲染方按下标取，不必猜 key
  const collisions = [];
  (nodes || []).forEach((node, index) => {
    let key = nodeId(node, index);
    if (Object.prototype.hasOwnProperty.call(positions, key)) {
      // 同名节点不覆盖——覆盖等于凭空少一台设备。改用带序号的次键错开。
      collisions.push({ key, message: `有多个节点同名为「${key}」，图上无法区分，已错开摆放` });
      key = `${key}#${index}`;
    }
    const xy = DEFAULTS[index % DEFAULTS.length];
    positions[key] = xy;
    coords.push(xy);
  });
  return { positions, coords, collisions };
}

/** 取第 index 个节点的坐标。**渲染方必须走这里**，别自己拼 key。
 *
 * 同一个坑踩了两次，都是「让调用方自己算 key」造成的：
 *   ① 渲染端用 `node.id || node.name || \`node-${index}\``，而布局对无 id 的节点
 *      存的是序号的**字符串**（`'3'`）→ 查不到 → `const [x, y] = undefined`
 *      在浏览器里抛 TypeError、页面白屏
 *   ② 改成「主键查不到再退化到冲突键」也不对——主键**从不缺失**（它就是前一个
 *      同名节点的槽位），于是两台同名设备仍取到同一坐标，等于没修
 *
 * 所以布局直接按索引给出 `coords`，渲染按下标取，key 拼法只剩一处。
 */
export function positionOf(index, layout) {
  const xy = layout?.coords?.[index];
  return xy || null;
}

export function nodeId(node, index) {
  if (node === null || node === undefined) return String(index);
  if (typeof node === 'string') return node;
  return String(node.id ?? node.name ?? index);
}

/** 连线两端的坐标。端点缺失时返回 missing，交由调用方处理。 */
export function resolveEndpoints(link, positions) {
  const srcKey = link?.src ?? link?.source ?? link?.from;
  const dstKey = link?.dst ?? link?.target ?? link?.to;
  const src = positions[srcKey];
  const dst = positions[dstKey];
  return {
    src, dst, srcKey, dstKey,
    missing: [src ? null : srcKey, dst ? null : dstKey].filter((k) => k !== null && k !== undefined),
  };
}
