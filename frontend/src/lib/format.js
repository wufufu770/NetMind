// 展示层纯函数。原先这三个函数埋在 App.jsx 里（该文件 1885 行），
// 无法单独测试——前端此前零测试。抽出来是为了能测，不是为了重构好看。
// 行为与原实现逐字一致，改动只在此处发生。

export function compactLabel(value, max = 12) {
  const raw = value || '--';                       // 同原实现：falsy 走占位符
  if (raw === '--') return '--';                   // 原实现的 bug：占位符 '--' 会被
                                                   // 下面的 [_-]+→' ' 规则吃成单个空格，
                                                   // 于是空值处从来没显示成 '--'。先短路返回。
  const text = String(raw).replace(/^free_/, '').replace(/[_-]+/g, ' ');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

const TOOL_ALIASES = {
  free_latency_probe: '内置延迟探测',
  free_bandwidth_estimator: '内置带宽估算',
  free_path_finder: '内置路径计算',
  free_sla_estimator: '内置 SLA 评估',
  free_acl_conflict_scan: '内置 ACL 冲突扫描',
  free_policy_diff: '内置策略差异分析',
  free_cron_explain: '内置调度解释',
  free_template_recommender: '内置模板推荐',
  free_rollback_preview: '内置回滚预览',
  free_anomaly_classifier: '内置异常分类',
  free_healing_advisor: '内置处置建议',
  free_state_explainer: '内置状态解释',
  free_workflow_selector: '内置流程选择',
};

export function displayToolName(name) {
  const raw = String(name || '');
  return TOOL_ALIASES[raw] || raw.replace(/^free_/, 'builtin_').replace(/_/g, ' ');
}

export function executionLabel(execution) {
  if (!execution) return '未选择';
  return execution.intent?.business || execution.status || '执行记录';
}

export function localizeJsonText(text) {
  return String(text)
    .replace(/\bdry_run\b/g, '试运行模式')
    .replace(/ACL_PRIORITY_OVERLAP/g, '访问控制优先级重叠')
    .replace(/PATH_UNREACHABLE/g, '路径不可达')
    .replace(/SLA_RISK/g, 'SLA 风险')
    .replace(/\bintent-[a-z0-9-]+\b/gi, '意图执行')
    .replace(/\bexec-[a-z0-9-]+\b/gi, '执行记录')
    .replace(/free_/g, 'builtin_')
    .replace(/free_builtin/g, 'builtin_tool');
}

export { TOOL_ALIASES };
