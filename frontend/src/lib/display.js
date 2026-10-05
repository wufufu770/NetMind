/** 展示层的取值决策：算不出来就显示「没有」，不拿一个像样的数字占位。
 *
 * 这些逻辑此前散在 `App.jsx` 的各个组件里（1859 行文件），**没有一行测试**。
 * 之前真出过事：`healthScore` 写成 `metrics.sla || (packet_loss < 0.01 ? 96 : 82)`——
 * SLA 字段为空时用丢包率反推一个 96/82，凭一个阈值编出整块面板最显眼的那个数。
 * 改动时没人发现，因为它「看起来是正常的」。
 *
 * 抽出来不是为了好看，是为了能测：这些是**用户被告知什么**的决策点，
 * 错了就是又一次谎报。
 */

/** 指标卡片的取值。null/undefined 一律显示占位符，不显示 0。
 *
 * 0 和「没有数据」是两件事：0 是测出来的零，占位符是压根没测到。
 * 把它们混成同一个显示，等于把「没测」说成「测了，是 0」。 */
export function metricValue(value, placeholder = '--') {
  if (value === null || value === undefined || value === '') return placeholder;
  if (typeof value === 'number' && !Number.isFinite(value)) return placeholder;
  return value;
}

/** 健康分。算不出来就是 null——不是 0，更不是按丢包率反推的默认值。
 *
 * 健康分需要事先约定的 SLO 目标才有意义；项目里没有这个目标，
 * 于是后端给 null。此时显示 '--' 并把原因说清楚。 */
export function healthScore(sla) {
  const n = Number(sla);
  if (sla === null || sla === undefined || sla === '' || !Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, n));
}

/** 健康环的绘制值。null 时画空环（0），但**文字仍显示 '--'**——
 * 画成 0 会让人以为「测了，是 0 分」。 */
export function healthRing(score) {
  const s = healthScore(score);
  return { drawn: s === null ? 0 : s, label: s === null ? '--' : s };
}

/** 指标卡的色调。数据缺失时用 neutral（中性），不用 ok——
 * 「ok」是在声称状态良好，而没有数据时我们并不知道状态如何。 */
export function metricTone(value, thresholds = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'neutral';
  const { warnAbove, badAbove } = thresholds;
  const n = Number(value);
  if (badAbove !== undefined && n >= badAbove) return 'bad';
  if (warnAbove !== undefined && n >= warnAbove) return 'warn';
  return 'ok';
}

/** 验证摘要里每一格的显示。
 *
 * `undefined` = 后端没给这项判断，显示「未知」——这是**如实**。
 * 早前这里写过 `sla_feasible: true` 与 `sla_confidence: 1`，
 * 于是「未知」被显示成「可行 100%」。 */
export function summaryCell(value, { yes, no, unknown = '未知' } = {}) {
  if (value === undefined) return { text: unknown, tone: 'neutral' };
  if (!value) return { text: no ?? '否', tone: value === false ? 'warn' : 'neutral' };
  return { text: yes ?? '是', tone: 'ok' };
}

/** 置信度显示。null/undefined 显示占位符，不显示 0%。 */
export function confidenceText(value, placeholder = '—') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return placeholder;
  return `${Math.round(Number(value) * 100)}%`;
}

/** 只读身份下该不该禁用写操作。
 *
 * 服务端早就按凭据档位拦了写操作（`NETMIND_READONLY_TOKEN` → 403），
 * 但界面看不出自己是只读：按钮照常可点，点了才知道不行。
 * 「点了才知道」比「没有这个按钮」更让人困惑——他会以为是系统故障。
 *
 * 判断依据是 `/api/system/status` 的 `auth_mode`，那是服务端在中间件里
 * 判定的真实档位，不是前端自己猜的。
 */
export function isReadonly(authMode) {
  return authMode === 'readonly-token';
}

/** 写操作按钮的呈现。返回 disabled / title（悬停说明为什么点不了）。 */
export function writeAction(authMode, label = '该操作') {
  if (!isReadonly(authMode)) return { disabled: false, title: '' };
  return {
    disabled: true,
    title: `当前是只读身份，${label}需要管理员凭据（NETMIND_ADMIN_TOKEN）`,
  };
}

/** 比率显示成百分比。null/undefined 显示占位符，**不显示 0%**。
 *
 * 面板上真实出现过这个矛盾：后端返回 `packet_loss: null`（没数据），
 * 前端却用 `Number(x || 0)` 渲染成「丢包率 0.00%」——同一张卡片里
 * 延迟显示 `--`、丢包显示 0%，等于把「没测」说成「测了，是 0」。
 * 那个 `|| 0` 躲在模板字符串里，躲过了 metricValue 的检查。
 */
export function percentText(value, placeholder = '--') {
  if (value === null || value === undefined || value === '') return placeholder;
  const n = Number(value);
  if (!Number.isFinite(n)) return placeholder;
  return `${(n * 100).toFixed(2)}%`;
}

/** 设备状态标签。
 *
 * 原写法 `node.ip || node.status || '可用'`：一台既没有 IP 也没有状态的设备，
 * 在界面上被标成「**可用**」。没有任何数据这么说——这是凭空的健康断言，
 * 而恰恰是网络运维工具最不该编的一件事。同理 `row.source || 'system'`
 * 会把「来源未标注」说成「来自 system」，直接抵消后端那套
 * `source=real|simulated|lab` 的来源标注；`row.ts ? … : '刚刚'` 把
 * 没有时间戳的记录说成「刚刚」。
 */
export function deviceStateLabel(node) {
  if (!node) return '状态未知';
  // 逐个判「有没有值」，而不是用 ?? —— 空字符串也是「没给」，
  // ?? 只在 null/undefined 时回退，{ip:'', status:'degraded'} 会被误判成未知
  for (const v of [node.ip, node.status]) {
    if (v !== undefined && v !== null && v !== '') return String(v);
  }
  return '状态未知';
}

/** 遥测/日志的来源标签。缺来源就说缺，不替它编一个。 */
export function provenanceLabel(row) {
  const v = row?.source ?? row?.src;
  return v === undefined || v === null || v === '' ? '来源未标注' : String(v);
}

// locale 标成可选：省略时用运行时默认。写成必填会既骗读者、
// 又让调用点与声明的参数个数对不上（正是本文件那三处踩过的坑）。
export function timeLabel(row, locale = undefined) {
  const ts = row?.ts ?? row?.timestamp;
  if (ts === undefined || ts === null || ts === '') return '时间未标注';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '时间未标注';
  return d.toLocaleString(locale);
}

/** 侧栏「全网状态」标签。**三态，不是两态。**
 *
 * 原写法 `health?.alerts ? \`${health.alerts} 告警\` : '正常'`：`health` 初始
 * 是 `null`，于是**任何检查都还没跑过**时，侧栏就显示绿色对勾 + 「正常」。
 * 那是整块界面上最要紧的一句谎报——「全网正常」。
 * 紧挨着的模型那行本来就是三态（离线/在线/检查），这里补齐成一致。
 */
export function netStatusLabel(health) {
  if (!health) return '未检查';
  const alerts = health.alerts;
  if (typeof alerts === 'number' && alerts > 0) return `${alerts} 告警`;
  if (alerts === 0) return '正常';
  return '未检查';      // 拿到了响应但没有可判的告警数——不当成「正常」
}

/** 写方法请求的客户端拦截。**集中在一处，不在每个按钮上。**
 *
 * 此前只在「触发自愈」一个操作上做了 `writeAction` 守卫——全站 41 个写操作里
 * **只有 1 个被拦**。诚实表声称「面板提前告知，而不是让只读用户点进去撞 403」，
 * 实际是：横幅会弹，但其余 40 个按钮照点不误，照样吃服务端 403。
 *
 * 放在 `request()` 里统一判断的理由：41 处各写一遍守卫，新增操作时一定会漏；
 * 而「只读身份不许写」本来就是**一条规则**，不是一个按钮的属性。
 */
