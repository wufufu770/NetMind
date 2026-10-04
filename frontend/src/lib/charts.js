/** 图表取点与列表检索。
 *
 * 两个都是「把缺数据变成一个看起来合理的值」的高发处。
 *
 * ## sparklinePoints
 *
 * 原实现 `Number(x[field] || 0)`：测不到的字段被当成 0，于是延迟图上会画出一条
 * 真实的「0ms」读数——比缺测更坏，因为它看起来是个好消息。遥测字段改成可缺
 * 之后（`latency_ms` 可能是 `null`），这条路更是直接被打开。
 *
 * 另一个坑：`Number('abc')` 是 NaN，NaN 进了 `points` 属性，整条 polyline 就
 * 不渲染了——**一个坏行毁掉整张图**，而且 SVG 不会报错，只是空着。
 *
 * 这里：取不到值就**不画那个点**（不补 0），坐标夹在视口内，并把丢掉的点数
 * 回报出去，让调用方能如实说「有 N 个采样没画」。
 */

/** 视口与留白。原实现的坐标系：x 铺满 0–100，y 留出上下各 14% 的余量。 */
const TOP_PAD = 14;
const HEIGHT = 100;
const BOTTOM = HEIGHT - TOP_PAD;   // 86

/**
 * 行 → 折线坐标串。返回 { points, drawn, dropped, empty }。
 * `points` 为空串表示没有可画的点（调用方据此显示占位，不要画一条空折线）。
 */
export function sparklinePoints(rows, field, { width = 100, height = HEIGHT } = {}) {
  const usable = [];
  rows = Array.isArray(rows) ? rows : [];
  rows.forEach((row, index) => {
    const raw = row == null ? null : row[field];
    const n = raw === null || raw === undefined || raw === '' ? NaN : Number(raw);
    if (Number.isFinite(n)) usable.push({ index, value: n });
    // 测不到 / 非数值 / 空串 —— 一律不进 usable，绝不用 0 顶替
  });

  const dropped = rows.length - usable.length;
  if (!usable.length) {
    return { points: '', drawn: 0, dropped, empty: true };
  }

  const values = usable.map((u) => u.value);
  const min = Math.min(0, ...values);          // 负值也留在视口内
  const max = Math.max(...values);
  const span = max - min || 1;                 // 全等时避免除零
  const usableRange = usable.length > 1 ? usable.length - 1 : 1;
  const floor = height - TOP_PAD;              // 14
  const band = Math.max(height - 2 * TOP_PAD, 1);   // 72：上下各留 14%
  // 按「有效点」均匀排布，而不是按原始下标——丢掉中间某个点不该让线断开
  const points = usable.map((u, i) => {
    const x = (i / usableRange) * width;
    const ratio = (u.value - min) / span;
    // 值域映射到 [floor-band, floor] 这条带子，clamp 只作越界的安全网。
    // 之前直接 clamp 到 [floor, height] 会把带子外的有效值也压成 floor：
    // 12.4 与 11.8 两个不同的值渲染成同一个 y，图看起来「没变化」——
    // **clamp 毁掉了数据**。
    // 沿用原实现的坐标方向：值越大 y 越小（线越高）。
    const y = floor - ratio * band;
    return `${round(x)},${round(clamp(y, 0, height))}`;
  }).join(' ');

  return { points, drawn: usable.length, dropped, empty: false };
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

function round(v) {
  return Math.round(v * 100) / 100;
}

/** 列表按关键词过滤：在整行的 JSON 上做不区分大小写的包含匹配。
 *
 * 抽出是因为它在两个页面里各写了一份（Agent 列表、审计日志），改一处漏一处的
 * 风险实在。空关键词返回全部——不是「匹配空串」的特殊情况，而是本来就该全显示。
 */
export function matchesKeyword(row, keyword) {
  const q = String(keyword ?? '').trim().toLowerCase();
  if (!q) return true;
  return JSON.stringify(row ?? null).toLowerCase().includes(q);
}

// 直白的两参，不做柯里化：`filterByKeyword(rows)(q)` 这种写法让调用点的
// 参数个数与声明对不上，门禁的 arity 检查只能靠特例放行——而「靠特例放行」
// 正是检查失效的开始。只有两个调用点，可读性比花招重要。
export function filterByKeyword(rows, keyword) {
  const list = Array.isArray(rows) ? rows : [];
  return list.filter(r => matchesKeyword(r, keyword));
}
