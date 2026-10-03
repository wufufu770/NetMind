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
