/** 工作流图的「图 ⇄ 可编辑文本」互转。
 *
 * UI 让用户直接编辑节点与边的文本，保存时再解析回结构。这是**往返转换**——
 * 序列化丢信息、解析吞输入，两边都容易静默出错，而错的结果看起来完全正常：
 * 画布照常渲染，只是少了一条边。
 *
 * 原实现里 `.filter((e) => e.length === 2)` 把不合法的边直接丢掉，用户打
 * `a -> b -> c` 什么提示都收不到，图上那条边就没了。静默丢数据比报错更糟，
 * 所以这里把问题**收集起来返回**，由调用方决定怎么提示。
 */

/** 结构 → 可编辑文本。 */
export function graphToText(graph) {
  const nodes = (graph?.nodes || []).map((n) => String(n).trim()).filter(Boolean);
  const edges = (graph?.edges || []).map((e) => {
    if (Array.isArray(e)) return e.join(' -> ');
    if (e && typeof e === 'object') {
      const src = e.source ?? e.src ?? e.from;
      const dst = e.target ?? e.dst ?? e.to;
      return `${src} -> ${dst}`;
    }
    return String(e);
  }).filter((line) => line && !line.includes('undefined'));
  return { nodesText: nodes.join('\n'), edgesText: edges.join('\n') };
}

/** 可编辑文本 → 结构。顺带返回 `problems`，不把坏行悄悄吞掉。
 *
 * 一行边必须是 `A -> B` 恰好两段。写成 `A -> B -> C`、缺箭头、或箭头方向反了
 * （`B <- A`）都会被记进 problems——这些此前都表现为「边没了」。
 */
export function textToGraph(nodesText, edgesText) {
  const nodes = String(nodesText ?? '').split('\n')
    .map((x) => x.trim()).filter(Boolean);
  const problems = [];

  const edges = [];
  String(edgesText ?? '').split('\n').forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    const parts = line.split('->').map((x) => x.trim()).filter((x) => x !== '');
    if (parts.length === 2) {
      edges.push(parts);
      return;
    }
    if (line.includes('<-')) {
      // 方向写反了是常见笔误。可自动纠正的就不该只报错让人自己找。
      const flipped = line.split('<-').map((x) => x.trim()).filter((x) => x !== '');
      if (flipped.length === 2) {
        edges.push([flipped[1], flipped[0]]);
        problems.push({ line: i + 1, text: line, kind: 'reversed', fixed: true,
                        message: `第 ${i + 1} 行箭头方向反了，已自动纠正为 ${flipped[1]} -> ${flipped[0]}` });
        return;
      }
    }
    problems.push({ line: i + 1, text: line, kind: 'malformed', fixed: false,
                    message: `第 ${i + 1} 行无法解析为「起点 -> 终点」，已忽略：${line}` });
  });

  // 指向不存在节点的边：结构上合法，图上却是一条连不到东西的线。
  const known = new Set(nodes);
  for (const [s, t] of edges) {
    for (const end of [s, t]) {
      if (!known.has(end)) {
        problems.push({ line: null, text: `${s} -> ${t}`, kind: 'unknown-endpoint',
                        fixed: false,
                        message: `边「${s} -> ${t}」的端点「${end}」不在节点列表里，`
                          + `画出来会是一条连不到东西的线` });
      }
    }
  }
  return { nodes, edges, problems };
}
