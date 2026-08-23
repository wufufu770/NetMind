import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Copy,
  Database,
  Download,
  Edit3,
  Eye,
  FileText,
  Gauge,
  KeyRound,
  LayoutDashboard,
  Network,
  Palette,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Save,
  ScrollText,
  Search,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Type,
  Upload,
  Wand2,
  Workflow,
  X,
  XCircle,
} from 'lucide-react';
import './style.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const pageDefs = [
  ['dashboard', '监控', '运行态势', LayoutDashboard, true],
  ['telemetry', '监控', '网络遥测', Activity, true],
  ['logs', '监控', '审计日志', ScrollText, true],
  ['intent', '管理', '意图编排', Radio, true],
  ['agents', '管理', 'Agent 管理', Bot, true],
  ['verification', '管理', '策略中心', ShieldCheck, true],
  ['workflow', '管理', '工作流编排', Workflow, true],
  ['reports', '管理', '合规报告', FileText, true],
  ['features', '管理', '系统自检', ClipboardCheck, true],
  ['config', '管理', '系统配置', Settings, true],
];

const themePresets = {
  aurora: {
    name: '极夜蓝',
    primary: '#4D8DFF',
    accent: '#68D391',
    background: '#09111F',
    side: '#07101C',
    card: '#111C2E',
    cardSoft: '#17243A',
    text: '#E6EDF7',
    muted: '#96A7BD',
    border: '#29405E',
    shadow: 'rgba(8, 18, 34, .42)',
  },
  graphite: {
    name: '石墨灰',
    primary: '#D9A441',
    accent: '#8AB4B8',
    background: '#121210',
    side: '#0C0C0B',
    card: '#1D1C19',
    cardSoft: '#27251F',
    text: '#F3EFE5',
    muted: '#B4AB9B',
    border: '#3A352B',
    shadow: 'rgba(0, 0, 0, .38)',
  },
  porcelain: {
    name: '瓷白日间',
    primary: '#2558D8',
    accent: '#0E8F74',
    background: '#F5F2EA',
    side: '#ECE6DA',
    card: '#FFFDF7',
    cardSoft: '#F0E9DC',
    text: '#1E2630',
    muted: '#66717F',
    border: '#D8CFBF',
    shadow: 'rgba(68, 49, 25, .18)',
  },
  forest: {
    name: '松林绿',
    primary: '#71A96C',
    accent: '#D6A853',
    background: '#0E1711',
    side: '#09100C',
    card: '#17251B',
    cardSoft: '#203229',
    text: '#EAF5E9',
    muted: '#A1B8A3',
    border: '#2C4834',
    shadow: 'rgba(1, 20, 8, .42)',
  },
};

const fontChoices = [
  { id: 'system', label: '系统清晰', family: 'ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif' },
  { id: 'serif', label: '仪表盘标题感', family: 'Georgia, "Times New Roman", "Songti SC", serif' },
  { id: 'mono', label: '工程等宽', family: '"SFMono-Regular", Consolas, "Liberation Mono", monospace' },
  { id: 'rounded', label: '圆润中文', family: '"Trebuchet MS", "PingFang SC", "Microsoft YaHei", sans-serif' },
];

const statusLabels = {
  waiting: '等待',
  running: '运行中',
  success: '成功',
  warning: '告警',
  failed: '失败',
  approval: '待审批',
  pending: '待处理',
  approved: '已批准',
  rejected: '已拒绝',
};

const issueCodeLabels = {
  ACL_PRIORITY_OVERLAP: '访问控制优先级重叠',
  SHADOWED_RULE: '存在被覆盖的规则',
  PATH_UNREACHABLE: '路径不可达',
  SLA_RISK: 'SLA 存在风险',
  SECURITY_BLOCK: '安全策略阻断',
};

function compactLabel(value, max = 12) {
  const text = String(value || '--').replace(/^free_/, '').replace(/[_-]+/g, ' ');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function displayToolName(name) {
  const raw = String(name || '');
  const aliases = {
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
  return aliases[raw] || raw.replace(/^free_/, 'builtin_').replace(/_/g, ' ');
}

function executionLabel(execution) {
  if (!execution) return '未选择';
  return execution.intent?.business || execution.status || '执行记录';
}

function localizeJsonText(text) {
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

const sampleIntents = [
  '今晚8点保障答辩视频会议，教师终端到会议服务器延迟低于50ms，访客网络限速5Mbps',
  '实验室网络隔离，只允许教师终端访问实验服务器',
  '访客网络限速5Mbps，并禁止访问实验室服务器',
  '凌晨2点到4点保障数据库备份链路，带宽不低于50Mbps',
  '保障内部 VoIP 通话低延迟，抖动低于10ms',
];

const fallbackModelPresets = [
  { id: 'deepseek', region: '国内', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', models: ['deepseek-v4-pro', 'deepseek-v4-flash'], default_model: 'deepseek-v4-pro', context_window: '128K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'qwen', region: '国内', name: '阿里百炼 Qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3.6-max-preview', 'qwen3.6-plus', 'qwen3.6-flash', 'qwen-turbo', 'qwen3-coder-plus'], default_model: 'qwen3.6-plus', context_window: '128K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'zhipu', region: '国内', name: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-5.1', 'glm-5', 'glm-4.7', 'glm-4.7-flash'], default_model: 'glm-5.1', context_window: '128K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'moonshot', region: '国内', name: 'Moonshot Kimi', base_url: 'https://api.moonshot.ai/v1', models: ['kimi-k2.6', 'kimi-k2.5'], default_model: 'kimi-k2.6', context_window: '256K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'minimax', region: '国内', name: 'MiniMax', base_url: 'https://api.minimax.chat/v1', models: ['minimax-m2.5'], default_model: 'minimax-m2.5', context_window: '128K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'openai', region: '国际', name: 'OpenAI', base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4o-mini', 'o4-mini'], default_model: 'gpt-4o', context_window: '128K', supports_thinking: true, api_style: 'openai-compatible' },
  { id: 'anthropic', region: '国际', name: 'Anthropic', base_url: 'https://api.anthropic.com/v1', models: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'], default_model: 'claude-sonnet-4-6', context_window: '200K', supports_thinking: true, api_style: 'anthropic' },
  { id: 'gemini', region: '国际', name: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta', models: ['gemini-2.5-pro', 'gemini-2.5-flash'], default_model: 'gemini-2.5-pro', context_window: '1M', supports_thinking: true, api_style: 'gemini' },
  { id: 'ollama', region: '其他', name: 'Ollama 本地', base_url: 'http://localhost:11434/v1', models: [], default_model: '', context_window: '取决于本地模型', supports_thinking: false, api_style: 'openai-compatible' },
  { id: 'custom', region: '其他', name: '自定义', base_url: '', models: [], default_model: '', context_window: '自行填写', supports_thinking: false, api_style: 'openai-compatible' },
];

function normalizeList(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.items)) return data.items;
  if (typeof data === 'object') return Object.values(data);
  return [];
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const adminToken = localStorage.getItem('netmind-admin-token') || import.meta.env.VITE_ADMIN_TOKEN || 'netmind-local-admin';
  if (adminToken) headers['X-NetMind-Admin'] = headers['X-NetMind-Admin'] || adminToken;
  const init = { ...options, headers };
  if (init.body && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body);
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }
  const res = await fetch(API + path, init);
  const contentType = res.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const message = typeof payload === 'string' ? payload : payload.detail || JSON.stringify(payload);
    throw new Error(message);
  }
  return payload;
}

function useApi(path, initial = null, refreshKey = 0) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState('');
  const reload = async () => {
    if (!path) return;
    setLoading(true);
    setError('');
    try {
      setData(await request(path));
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    reload();
  }, [path, refreshKey]);
  return { data, setData, loading, error, reload };
}

function useLocalSettings() {
  const [settings, setSettings] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('netmind-ui-settings')) || {};
    } catch {
      return {};
    }
  });
  const merged = {
    theme: settings.theme || 'aurora',
    font: settings.font || 'system',
    fontSize: settings.fontSize || 1,
    density: settings.density || 'comfortable',
    ...settings,
  };
  useEffect(() => {
    localStorage.setItem('netmind-ui-settings', JSON.stringify(merged));
    const preset = themePresets[merged.theme] || themePresets.aurora;
    const font = fontChoices.find((f) => f.id === merged.font) || fontChoices[0];
    const root = document.documentElement;
    Object.entries(preset).forEach(([key, value]) => {
      if (key !== 'name') root.style.setProperty(`--${key}`, value);
    });
    root.style.setProperty('--font-family', font.family);
    root.style.setProperty('--font-scale', String(merged.fontSize));
    root.dataset.density = merged.density;
  }, [merged.theme, merged.font, merged.fontSize, merged.density]);
  return [merged, (patch) => setSettings((prev) => ({ ...prev, ...patch }))];
}

function toastMessage(setToast, type, text) {
  setToast({ type, text, id: Date.now() });
}

function copyText(text, setToast) {
  const value = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  navigator.clipboard?.writeText(value || '').then(
    () => toastMessage(setToast, 'success', '已复制到剪贴板'),
    () => toastMessage(setToast, 'warn', '浏览器不允许复制，请手动选择内容')
  );
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function Shell() {
  const [page, setPage] = useState('dashboard');
  const [toast, setToast] = useState(null);
  const [settings, updateSettings] = useLocalSettings();
  const [health, setHealth] = useState(null);
  const [modelHealth, setModelHealth] = useState(null);
  const [globalRefresh, setGlobalRefresh] = useState(0);
  const title = pageDefs.find((p) => p[0] === page) || pageDefs[0];

  const runHealth = async () => {
    try {
      const data = await request('/api/system/status');
      setHealth(data);
      toastMessage(setToast, data.healthy ? 'success' : 'warn', data.healthy ? '全网健康检查通过' : '检测到网络告警');
    } catch (err) {
      toastMessage(setToast, 'error', `健康检查失败：${err.message}`);
    }
  };

  const runModelCheck = async () => {
    try {
      const data = await request('/api/system/model-health-check', { method: 'POST' });
      setModelHealth(data);
      toastMessage(setToast, data.llm_available ? 'success' : 'warn', data.llm_available ? '模型在线' : '模型不可用，已降级到规则引擎');
    } catch (err) {
      toastMessage(setToast, 'error', `模型检查失败：${err.message}`);
    }
  };

  const resetRuntime = async () => {
    try {
      await request('/api/config/reset-runtime', { method: 'POST' });
      setGlobalRefresh((x) => x + 1);
      toastMessage(setToast, 'success', '运行态数据已清空');
    } catch (err) {
      toastMessage(setToast, 'error', `清空失败：${err.message}`);
    }
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">跳到内容</a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div>
            <strong>网脉 NetMind</strong>
            <small>自治网络控制台</small>
          </div>
        </div>
        <nav>
          {['监控', '管理'].map((group) => (
            <div key={group} className="nav-group">
              <label>{group}</label>
              {pageDefs
                .filter((p) => p[1] === group && p[4] !== false)
                .map(([id, , name, Icon]) => (
                  <button key={id} type="button" onClick={() => setPage(id)} className={page === id ? 'active' : ''}>
                    <Icon size={17} />
                    <span>{name}</span>
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-panel status-panel">
          <button type="button" className="status-line" onClick={runHealth}>
            <CheckCircle2 size={15} className={health?.alerts ? 'warn-text' : 'ok-text'} />
            <span>全网状态</span>
            <b>{health?.alerts ? `${health.alerts} 告警` : '正常'}</b>
          </button>
          <button type="button" className="status-line" onClick={runModelCheck}>
            <Sparkles size={15} className={modelHealth?.llm_available === false ? 'warn-text' : 'ok-text'} />
            <span>模型</span>
            <b>{modelHealth?.llm_available === false ? '离线' : modelHealth?.mode ? '在线' : '检查'}</b>
          </button>
        </div>
      </aside>

      <main className="main" id="content">
        <header className="topbar">
          <div>
            <h1>{title[2]}</h1>
          </div>
          <div className="top-actions">
            <button type="button" onClick={() => setGlobalRefresh((x) => x + 1)}><RefreshCw size={16} />刷新</button>
            <button type="button" onClick={resetRuntime} className="subtle"><RotateCcw size={16} />清空</button>
            <button type="button" className="primary" onClick={() => setPage('intent')}><Plus size={16} />新建意图</button>
          </div>
        </header>
        <section className="page-body">
          {page === 'dashboard' && <Dashboard setPage={setPage} setToast={setToast} refreshKey={globalRefresh} />}
          {page === 'intent' && <IntentConsole setPage={setPage} setToast={setToast} />}
          {page === 'agents' && <Agents setToast={setToast} />}
          {page === 'verification' && <Verification setToast={setToast} />}
          {page === 'workflow' && <WorkflowPage setToast={setToast} />}
          {page === 'telemetry' && <Telemetry setToast={setToast} />}
          {page === 'logs' && <Logs setToast={setToast} refreshKey={globalRefresh} />}
          {page === 'reports' && <Reports setToast={setToast} />}
          {page === 'features' && <FeatureAcceptance setPage={setPage} setToast={setToast} />}
          {page === 'config' && <ConfigCenter settings={settings} updateSettings={updateSettings} setToast={setToast} />}
        </section>
      </main>
      {toast && <Toast toast={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

function Toast({ toast, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3800);
    return () => clearTimeout(t);
  }, [toast?.id]);
  const Icon = toast.type === 'success' ? CheckCircle2 : toast.type === 'error' ? XCircle : AlertTriangle;
  return (
    <div className={`toast ${toast.type}`}>
      <Icon size={18} />
      <span>{toast.text}</span>
      <button type="button" onClick={onClose} aria-label="关闭提示"><X size={14} /></button>
    </div>
  );
}

function Card({ children, className = '', title, action }) {
  return (
    <article className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          {title && <h3>{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </article>
  );
}

function EmptyState({ icon: Icon = Database, title, text, action }) {
  return (
    <div className="empty-state">
      <Icon size={30} />
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

function JsonBlock({ data, setToast, maxHeight = 360 }) {
  const text = typeof data === 'string' ? data : JSON.stringify(data ?? {}, null, 2);
  const displayText = localizeJsonText(text);
  return (
    <div className="json-box" style={{ maxHeight }}>
      <button type="button" className="copy-mini" onClick={() => copyText(text, setToast)}><Copy size={13} />复制</button>
      <pre>{displayText}</pre>
    </div>
  );
}

function StatCard({ label, value, unit, tone = 'neutral', hint, subMetrics, icon: Icon = Activity, onClick }) {
  const content = <>
    <span className="stat-icon"><Icon size={18} /></span>
    <small>{label}</small>
    <strong>{value ?? '--'}{unit && <em>{unit}</em>}</strong>
    {subMetrics ? <span className="sub-metrics">{subMetrics}</span> : <span>{hint}</span>}
  </>;
  return onClick ? <button type="button" className={`stat-card ${tone}`} onClick={onClick}>{content}</button> : <div className={`stat-card ${tone}`}>{content}</div>;
}

function HealthRing({ score }) {
  const safe = Number.isFinite(Number(score)) ? Math.max(0, Math.min(100, Number(score))) : 0;
  const dash = `${safe} ${100 - safe}`;
  return (
    <div className="health-ring" role="img" aria-label={`健康分 ${safe}`}>
      <svg viewBox="0 0 42 42">
        <circle className="ring-bg" cx="21" cy="21" r="15.9" />
        <circle className="ring-fg" cx="21" cy="21" r="15.9" strokeDasharray={dash} />
      </svg>
      <div><span>{score ?? '--'}</span><small>健康分</small></div>
    </div>
  );
}

function Dashboard({ setPage, setToast, refreshKey }) {
  const { data, loading, error, reload } = useApi('/api/dashboard', null, refreshKey);
  const metrics = data?.metrics || {};
  const topology = data?.topology || { nodes: [], links: [] };
  const risks = (data?.risks || []).filter((risk) => risk.severity !== 'success');
  const events = data?.events || [];
  const healthScore = metrics.sla || (metrics.packet_loss < 0.01 ? 96 : 82);
  const alertCount = risks.length;

  return (
    <div className="stack gap-xl">
      <div className="hero-dashboard compact-hero">
        <div>
          <span className="eyebrow"><Activity size={14} />运行态势</span>
          <h2>全网状态一屏看清。</h2>
          <p>关注 SLA、延迟和告警；需要处理时直接进入策略中心。</p>
          <div className="button-row">
            <button type="button" className="primary" onClick={() => setPage('intent')}><Plus size={16} />新建意图</button>
            <button type="button" onClick={() => setPage('verification')}><ShieldCheck size={16} />策略中心</button>
            <button type="button" onClick={() => setPage('features')}><ClipboardCheck size={16} />系统自检</button>
            <button type="button" onClick={reload}><RefreshCw size={16} />刷新</button>
          </div>
        </div>
        <HealthRing score={loading ? null : healthScore} />
      </div>

      {error && <InlineError text={error} />}
      <div className="metrics-grid compact three">
        <StatCard label="SLA 达成率" value={metrics.sla} unit="%" tone="ok" hint="进入策略中心" icon={Gauge} onClick={() => setPage('verification')} />
        <StatCard label="端到端延迟" value={metrics.latency_ms} unit="ms" tone={metrics.latency_ms > 50 ? 'warn' : 'ok'} subMetrics={`丢包率 ${((Number(metrics.packet_loss || 0)) * 100).toFixed(2)}% · 吞吐 ${metrics.throughput_mbps ?? '--'} Mbps`} icon={Activity} onClick={() => setPage('telemetry')} />
        <StatCard label="活跃告警" value={alertCount} tone={alertCount ? 'warn' : 'ok'} hint={alertCount ? '需要处理' : '暂无异常'} icon={AlertTriangle} onClick={() => setPage(alertCount ? 'verification' : 'logs')} />
      </div>

      <div className="dashboard-grid compact-dashboard">
        <Card title="网络拓扑" action={<button type="button" onClick={() => copyText(topology, setToast)}><Copy size={14} />复制</button>}>
          <TopologyMap topology={topology} />
        </Card>
        <Card title="活跃告警" action={<button type="button" onClick={() => setPage('verification')}><Eye size={14} />处理</button>}>
          <div className="risk-list">
            {risks.length ? risks.map((risk, index) => (
              <button key={`${risk.title}-${index}`} type="button" onClick={() => setPage('verification')} className={`risk-row ${risk.severity}`}>
                <AlertTriangle size={18} />
                <span>{risk.title}</span>
                <ChevronRight size={16} />
              </button>
            )) : <EmptyState title="暂无异常" text="网络状态稳定。" icon={CheckCircle2} />}
          </div>
        </Card>
      </div>

      <Card title="最近事件" action={<button type="button" onClick={() => setPage('logs')}><ScrollText size={14} />审计日志</button>}>
        <Timeline rows={events} />
      </Card>
    </div>
  );
}

function TopologyMap({ topology }) {
  const nodes = topology?.nodes || [];
  const links = topology?.links || [];
  const positions = useMemo(() => {
    const defaults = [
      [50, 12], [18, 36], [82, 36], [18, 68], [50, 86], [82, 68], [50, 48], [8, 52], [92, 52],
    ];
    return nodes.reduce((acc, node, index) => {
      acc[node.id || node.name || index] = defaults[index % defaults.length];
      return acc;
    }, {});
  }, [nodes]);
  if (!nodes.length) return <EmptyState title="暂无拓扑" text="后端未返回拓扑节点。" icon={Network} />;
  return (
    <div className="topology-map">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {links.map((link, index) => {
          const src = positions[link.src || link.source || link.from] || positions[nodes[0]?.id] || [10, 10];
          const dst = positions[link.dst || link.target || link.to] || positions[nodes[1]?.id] || [90, 90];
          return <line key={index} x1={src[0]} y1={src[1]} x2={dst[0]} y2={dst[1]} />;
        })}
      </svg>
      {nodes.map((node, index) => {
        const id = node.id || node.name || `node-${index}`;
        const [x, y] = positions[id];
        return (
          <button key={id} type="button" className={`topo-node ${node.role || node.type || ''}`} style={{ left: `${x}%`, top: `${y}%` }} aria-label={`${id} ${node.role || node.type || ''}`}>
            <Server size={15} />
            <b>{compactLabel(node.label || id, 7)}</b>
            <span className="topo-tooltip">
              <strong>{id}</strong>
              <small>{node.role || node.type || 'node'} · {node.ip || node.status || '可用'}</small>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Timeline({ rows }) {
  if (!rows?.length) return <EmptyState title="还没有事件" text="提交一次意图或执行一次健康检查后，这里会出现时间线。" icon={ScrollText} />;
  return (
    <div className="timeline">
      {rows.slice().reverse().map((row, index) => (
        <div key={`${row.ts}-${index}`} className={`timeline-item ${row.level || 'info'}`}>
          <span className="dot" />
          <div>
            <b>{row.source || 'system'}</b>
            <p>{row.message || JSON.stringify(row)}</p>
            <small>{row.ts ? new Date(row.ts).toLocaleString() : '刚刚'}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function IntentConsole({ setPage, setToast }) {
  const [text, setText] = useState(sampleIntents[0]);
  const [dryRun, setDryRun] = useState(false);
  const [result, setResult] = useState(null);
  const [parseResult, setParseResult] = useState(null);
  const [compileResult, setCompileResult] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [loading, setLoading] = useState(false);
  const [workflowId, setWorkflowId] = useState('default');
  const [templateId, setTemplateId] = useState(`tpl-${Date.now().toString(36).slice(-4)}`);
  const [templateRefresh, setTemplateRefresh] = useState(0);
  const { data: workflowsData, reload: reloadWorkflows } = useApi('/api/workflows/catalog', [], templateRefresh);
  const { data: templatesData, setData: setTemplatesData, reload: reloadTemplates } = useApi('/api/template-manager/list', [], templateRefresh);
  const workflows = normalizeList(workflowsData);
  const templates = normalizeList(templatesData);

  const parse = async () => {
    setLoading(true);
    try {
      const data = await request('/api/intent/parse', { method: 'POST', body: { text, dry_run: dryRun, workflow_id: workflowId } });
      setParseResult(data);
      toastMessage(setToast, 'success', '意图已解析为 DSL');
    } catch (err) {
      toastMessage(setToast, 'error', `解析失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const compileDsl = async () => {
    setLoading(true);
    try {
      const data = await request('/api/intent/compile', { method: 'POST', body: { text, dry_run: dryRun, workflow_id: workflowId } });
      setCompileResult(data);
      setParseResult(data.dsl);
      toastMessage(setToast, data.validation?.valid ? 'success' : 'warn', data.validation?.valid ? 'DSL 编译与 Schema 校验通过' : 'DSL 编译完成但需要复核');
    } catch (err) {
      toastMessage(setToast, 'error', `编译失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    setLoading(true);
    try {
      const data = await request('/api/intent/submit', { method: 'POST', body: { text, dry_run: dryRun, workflow_id: workflowId } });
      setResult(data);
      setParseResult(data.intent);
      toastMessage(setToast, data.status === 'warning' ? 'warn' : 'success', '闭环执行已完成');
    } catch (err) {
      toastMessage(setToast, 'error', `提交失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const suggest = async () => {
    try {
      const data = await request('/api/template-manager/suggest', { method: 'POST', body: { text } });
      setSuggestion(data);
      toastMessage(setToast, 'success', '已生成模板建议');
    } catch (err) {
      toastMessage(setToast, 'error', `模板建议失败：${err.message}`);
    }
  };

  const saveTemplate = async () => {
    const tid = templateId.trim() || `tpl-${Date.now().toString(36)}`;
    try {
      const saved = await request('/api/template-manager/create', { method: 'POST', body: { template_id: tid, text } });
      setTemplateId(saved.template_id);
      setTemplateRefresh((x) => x + 1);
      toastMessage(setToast, 'success', '模板已保存到模板库');
    } catch (err) {
      toastMessage(setToast, 'error', `保存失败：${err.message}`);
    }
  };

  const deleteTemplate = async (templateIdToDelete) => {
    try {
      await request(`/api/template-manager/${encodeURIComponent(templateIdToDelete)}`, { method: 'DELETE' });
      setTemplatesData((prev) => normalizeList(prev).filter((item) => item.template_id !== templateIdToDelete));
      toastMessage(setToast, 'success', '模板已删除');
    } catch (err) {
      toastMessage(setToast, 'error', `删除失败：${err.message}`);
    }
  };

  return (
    <div className="intent-layout no-stretch">
      <Card className="panel-fixed" title="自然语言意图" action={<button type="button" onClick={() => copyText(text, setToast)}><Copy size={14} />复制</button>}>
        <div className="field">
          <label>执行工作流</label>
          <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} onFocus={reloadWorkflows}>
            {workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name || workflow.id}</option>)}
            {!workflows.length && <option value="default">默认闭环工作流</option>}
          </select>
        </div>
        <div className="field">
          <label>意图描述</label>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="输入业务目标、源和目的、SLA、限制、时间窗口等" />
        </div>
        <div className="sample-grid">
          {sampleIntents.map((sample) => (
            <button key={sample} type="button" onClick={() => setText(sample)}>{sample}</button>
          ))}
        </div>
        <label className="checkline"><input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />试运行模式，不下发</label>
        <div className="button-row">
          <button type="button" onClick={parse} disabled={loading}><Wand2 size={16} />解析意图</button>
          <button type="button" onClick={compileDsl} disabled={loading}><ClipboardCheck size={16} />编译校验</button>
          <button type="button" onClick={suggest}><Sparkles size={16} />模板建议</button>
          <button type="button" onClick={saveTemplate}><Save size={16} />保存模板</button>
          <button type="button" className="primary" onClick={submit} disabled={loading}><Play size={16} />提交闭环</button>
        </div>
        <div className="template-save-panel">
          <div className="field"><label>模板编号</label><input value={templateId} onChange={(e) => setTemplateId(e.target.value)} /></div>
          <small>保存位置：后端模板库，可在右侧“模板库”中应用、删除或再次保存。</small>
        </div>
      </Card>

      <Card title="Intent DSL 可视化" action={<button type="button" onClick={() => copyText(parseResult, setToast)}><Copy size={14} />复制 DSL</button>}>
        {parseResult ? <DslSummary intent={parseResult} /> : <EmptyState title="还未解析" text="解析或编译后显示。" icon={Radio} />}
        {compileResult?.validation && <div className="validation-panel"><h4>Schema 校验</h4><VerificationSummary report={{ passed: compileResult.validation.valid, reachable: true, sla_feasible: true, security_passed: true, rollback_ready: true, sla_confidence: compileResult.validation.valid ? 1 : .4 }} />{compileResult.validation.issues?.length ? <JsonBlock data={compileResult.validation} setToast={setToast} maxHeight={220} /> : <InlineSuccess text="IntentDSL Schema 校验通过。" />}</div>}
      </Card>

      <Card className="panel-scroll" title="执行链路" action={<button type="button" onClick={() => result && setPage('agents')} disabled={!result}><Bot size={14} />查看 Agent</button>}>
        {result?.steps?.length ? <AgentSteps steps={result.steps} setToast={setToast} /> : <EmptyState title="还没有执行链路" text="提交后显示执行链路。" icon={Bot} />}
      </Card>

      <Card className="panel-scroll" title="模板库与建议" action={<button type="button" onClick={reloadTemplates}><RefreshCw size={14} />刷新</button>}>
        {suggestion ? <TemplateSuggestion data={suggestion} setText={setText} /> : <InlineSuccess text="点击“模板建议”后，会显示相似模板和保存建议。" />}
        <div className="template-list managed">
          {templates.map((item) => (
            <div className="template-row" key={item.template_id}>
              <button type="button" onClick={() => setText(item.text)}>
                <b>{item.template_id}</b>
                <small>{item.business || 'custom'} · 模板库</small>
                <span>{item.text}</span>
              </button>
              <button type="button" className="subtle" onClick={() => deleteTemplate(item.template_id)} aria-label="删除模板"><X size={14} />删除</button>
            </div>
          ))}
          {!templates.length && <EmptyState title="模板库为空" text="保存模板后会出现在这里。" icon={Database} />}
        </div>
        <JsonBlock data={result || { message: '等待结果' }} setToast={setToast} maxHeight={230} />
      </Card>
    </div>
  );
}

function DslSummary({ intent }) {
  const chips = [intent.business, intent.priority, intent.recover_policy, ...(intent.tags || [])].filter(Boolean);
  return (
    <div className="dsl-summary">
      <div className="chip-row">{chips.map((chip) => <span className="chip" key={chip}>{chip}</span>)}</div>
      <div className="kv-grid">
        <div><small>源</small><b>{intent.target?.src || '--'}</b></div>
        <div><small>目的</small><b>{intent.target?.dst || '--'}</b></div>
        <div><small>业务</small><b>{intent.business}</b></div>
        <div><small>优先级</small><b>{intent.priority}</b></div>
        <div><small>延迟</small><b>{intent.sla?.latency_ms ?? '--'}ms</b></div>
        <div><small>带宽</small><b>{intent.sla?.bandwidth_mbps ?? '--'}Mbps</b></div>
        <div><small>访客限速</small><b>{intent.constraints?.guest_limit_mbps ?? '--'}Mbps</b></div>
        <div><small>回滚</small><b>{intent.rollback_on_failure ? '开启' : '关闭'}</b></div>
      </div>
      {intent.ambiguous && <InlineWarn text={`该意图可能有歧义：${(intent.candidates || []).join(' / ')}`} />}
    </div>
  );
}

function TemplateSuggestion({ data, setText }) {
  return (
    <div className="stack">
      <div className="mini-row"><span>识别业务</span><b>{data.business}</b></div>
      <div className="mini-row"><span>建议保存</span><b>{data.should_save ? '是' : '否'}</b></div>
      <div className="template-list">
        {(data.similar_templates || []).map((item) => (
          <button key={item.template_id} type="button" onClick={() => setText(item.text)}>
            <b>{item.template_id}</b>
            <span>{item.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AgentSteps({ steps, setToast }) {
  return (
    <div className="agent-steps">
      {steps.map((step, index) => (
        <button key={`${step.agent}-${index}`} type="button" className={`step-card ${step.status}`} onClick={() => copyText(step, setToast)} title="点击复制该智能体步骤详情">
          <span>{index + 1}</span>
          <div>
            <b>{step.agent}</b>
            <small>{statusLabels[step.status] || step.status} · {step.duration_ms || 0}ms</small>
          </div>
          <ChevronRight size={15} />
        </button>
      ))}
    </div>
  );
}

function Agents({ setToast }) {
  const { data: agentsData, loading, error, reload, setData } = useApi('/api/config/agents', []);
  const { data: modelsData } = useApi('/api/config/models', []);
  const { data: executions } = useApi('/api/executions', []);
  const agents = normalizeList(agentsData);
  const models = normalizeList(modelsData);
  const [query, setQuery] = useState('');
  const [selectedName, setSelectedName] = useState('');
  const selected = agents.find((a) => a.name === selectedName) || agents[0];
  const [draft, setDraft] = useState(null);
  const [schedule, setSchedule] = useState({ enabled: true, active_schedule: 'always' });

  useEffect(() => {
    if (selected) {
      setSelectedName(selected.name);
      setDraft({ ...selected, allowed_tools_text: (selected.allowed_tools || []).join(', ') });
      request(`/api/config/agents/${selected.name}/schedule`).then(setSchedule).catch(() => setSchedule({ enabled: true, active_schedule: 'always' }));
    }
  }, [selected?.name]);

  const filtered = agents.filter((agent) => JSON.stringify(agent).toLowerCase().includes(query.toLowerCase()));
  const lastExecution = normalizeList(executions).at(-1);

  const saveAgent = async () => {
    if (!draft?.name) return toastMessage(setToast, 'warn', 'Agent 名称不能为空');
    const payload = {
      name: draft.name,
      level: draft.level || 'secondary',
      model_id: draft.model_id || 'mock',
      allowed_tools: (draft.allowed_tools_text || '').split(',').map((x) => x.trim()).filter(Boolean),
      prompt: draft.prompt || '',
    };
    try {
      const saved = await request('/api/config/agents', { method: 'POST', body: payload });
      setData((prev) => {
        const rows = normalizeList(prev).filter((a) => a.name !== saved.name);
        return [...rows, saved];
      });
      toastMessage(setToast, 'success', '智能体配置已保存');
    } catch (err) {
      toastMessage(setToast, 'error', `保存失败：${err.message}`);
    }
  };

  const saveSchedule = async () => {
    try {
      const saved = await request(`/api/config/agents/${draft.name}/schedule`, { method: 'PUT', body: schedule });
      setSchedule(saved);
      toastMessage(setToast, 'success', '调度配置已保存');
    } catch (err) {
      toastMessage(setToast, 'error', `调度保存失败：${err.message}`);
    }
  };

  const negotiate = async () => {
    try {
      const data = await request('/api/agents/negotiate', { method: 'POST', body: { goal: 'policy_coordination' } });
      toastMessage(setToast, data.agreed ? 'success' : 'warn', data.agreed ? '协商已达成一致' : '协商未达成一致');
    } catch (err) {
      toastMessage(setToast, 'error', `协商失败：${err.message}`);
    }
  };

  return (
    <div className="config-layout agents-page">
      <Card title="智能体列表" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新</button>}>
        <SearchBox value={query} onChange={setQuery} placeholder="搜索 Agent、工具、模型、提示词" />
        {error && <InlineError text={error} />}
        <div className="agent-list">
          {filtered.map((agent) => (
            <button key={agent.name} type="button" onClick={() => setSelectedName(agent.name)} className={agent.name === selectedName ? 'active' : ''}>
              <Bot size={18} />
              <div><b>{agent.name}</b><small>{agent.level} · {agent.model_id}</small></div>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
        {loading && <p className="muted">正在加载智能体...</p>}
      </Card>

      <Card title="智能体内容编辑" action={<button type="button" className="primary" onClick={saveAgent}><Save size={14} />保存 Agent</button>}>
        {draft ? (
          <div className="form-grid">
            <div className="field"><label>名称</label><input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
            <div className="field"><label>层级</label><select value={draft.level} onChange={(e) => setDraft({ ...draft, level: e.target.value })}><option value="primary">primary</option><option value="secondary">secondary</option><option value="tertiary">tertiary</option></select></div>
            <div className="field"><label>绑定模型</label><select value={draft.model_id} onChange={(e) => setDraft({ ...draft, model_id: e.target.value })}>{models.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}</select></div>
            <div className="field"><label>可用工具，逗号分隔</label><input value={draft.allowed_tools_text} onChange={(e) => setDraft({ ...draft, allowed_tools_text: e.target.value })} /></div>
            <div className="field span-2"><label>系统提示词 / 智能体职责</label><textarea value={draft.prompt || ''} onChange={(e) => setDraft({ ...draft, prompt: e.target.value })} /></div>
          </div>
        ) : <EmptyState title="没有可编辑 Agent" text="配置接口尚未返回 Agent 列表。" icon={Bot} />}
      </Card>

      <Card title="调度与运行控制" action={<button type="button" onClick={saveSchedule}><ClockIcon />保存调度</button>}>
        <div className="form-grid compact">
          <label className="checkline"><input type="checkbox" checked={schedule.enabled} onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })} />启用该智能体</label>
          <div className="field"><label>Cron / 调度窗口</label><input value={schedule.active_schedule || 'always'} onChange={(e) => setSchedule({ ...schedule, active_schedule: e.target.value })} /></div>
        </div>
        <div className="button-row">
          <button type="button" onClick={negotiate}><Network size={16} />跨域协商</button>
          <button type="button" onClick={() => copyText(draft, setToast)}><Copy size={16} />复制配置</button>
        </div>
      </Card>

      <Card title="最近执行链路">
        {lastExecution?.steps?.length ? <AgentSteps steps={lastExecution.steps} setToast={setToast} /> : <EmptyState title="暂无执行链路" text="提交意图后显示。" icon={Workflow} />}
      </Card>
    </div>
  );
}

function ClockIcon() {
  return <Activity size={14} />;
}

function Verification({ setToast }) {
  const { data: executions, reload } = useApi('/api/executions', []);
  const executionList = normalizeList(executions);
  const [selectedId, setSelectedId] = useState('');
  const selected = executionList.find((e) => e.execution_id === selectedId) || executionList.at(-1);
  const [customJson, setCustomJson] = useState('');
  const [manualResult, setManualResult] = useState(null);

  useEffect(() => {
    if (selected) setSelectedId(selected.execution_id);
  }, [selected?.execution_id]);

  const verifySelected = async () => {
    if (!selected?.policy_set) return toastMessage(setToast, 'warn', '该执行没有策略集，请先提交意图');
    try {
      const data = await request('/api/verification/check', { method: 'POST', body: { policy_set: selected.policy_set, intent: selected.intent || null } });
      setManualResult(data);
      toastMessage(setToast, data.passed ? 'success' : 'warn', data.passed ? '验证通过' : '验证发现问题');
    } catch (err) {
      toastMessage(setToast, 'error', `验证失败：${err.message}`);
    }
  };

  const autoFix = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '没有可修复的执行');
    try {
      const data = await request(`/api/policy/${selected.execution_id}/auto-fix`, { method: 'POST' });
      setManualResult(data);
      toastMessage(setToast, data.passed ? 'success' : 'warn', '已执行自动修复检查');
    } catch (err) {
      toastMessage(setToast, 'error', `自动修复失败：${err.message}`);
    }
  };

  const createApproval = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '请选择执行记录');
    try {
      const data = await request(`/api/approval-requests/from-execution/${selected.execution_id}`, { method: 'POST' });
      toastMessage(setToast, 'success', '审批单已创建');
    } catch (err) {
      toastMessage(setToast, 'error', `创建审批失败：${err.message}`);
    }
  };


  const deploySelected = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '请选择执行记录');
    try {
      const data = await request(`/api/deploy/${selected.execution_id}`, { method: 'POST' });
      // 指标取真实数据:security_passed 看逐命令结果,rollback_ready 看回滚计划是否非空
      const securityPassed = Array.isArray(data.executed) && data.executed.length > 0
        ? data.executed.every((c) => !c.blocked && !c.requires_approval)
        : data.success;
      let rollbackReady = false;
      try {
        const plan = await request(`/api/deploy/${selected.execution_id}/rollback-plan`);
        rollbackReady = Array.isArray(plan.rollback_commands) && plan.rollback_commands.length > 0;
      } catch { /* 计划获取失败时按 false 展示 */ }
      setManualResult({ deploy: data, passed: data.success, reachable: true, sla_feasible: true, security_passed: securityPassed, rollback_ready: rollbackReady, sla_confidence: data.success ? 1 : .4 });
      toastMessage(setToast, data.success ? 'success' : 'warn', data.success ? '配置已通过 TransactionManager 下发' : (data.rollback_complete === false ? '下发失败，自动回滚未全部完成' : '下发失败，已尝试回滚'));
    } catch (err) {
      toastMessage(setToast, 'error', `下发失败：${err.message}`);
    }
  };

  const rollbackSelected = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '请选择执行记录');
    try {
      const data = await request(`/api/deploy/${selected.execution_id}/rollback`, { method: 'POST' });
      setManualResult({ rollback: data, passed: data.success, reachable: true, sla_feasible: true, security_passed: data.success, rollback_ready: data.success, sla_confidence: data.success ? 1 : .4 });
      toastMessage(setToast, data.success ? 'success' : 'warn', data.success ? 'RollbackManager 已执行原子回滚' : '回滚执行存在失败命令');
    } catch (err) {
      toastMessage(setToast, 'error', `回滚失败：${err.message}`);
    }
  };

  const showRollbackPlan = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '请选择执行记录');
    try {
      const data = await request(`/api/deploy/${selected.execution_id}/rollback-plan`);
      setManualResult({ rollback_plan: data, passed: true, reachable: true, sla_feasible: true, security_passed: true, rollback_ready: true, sla_confidence: 1 });
      toastMessage(setToast, 'success', '回滚计划已生成');
    } catch (err) {
      toastMessage(setToast, 'error', `回滚计划失败：${err.message}`);
    }
  };

  const validateCustom = async () => {
    try {
      const payload = JSON.parse(customJson || '{}');
      const data = await request('/api/config/validate', { method: 'POST', body: payload });
      setManualResult(data);
      toastMessage(setToast, data.valid ? 'success' : 'warn', data.valid ? '配置验证通过' : '配置存在问题');
    } catch (err) {
      toastMessage(setToast, 'error', `自定义验证失败：${err.message}`);
    }
  };

  const issues = manualResult?.conflicts || selected?.verification?.conflicts || [];
  const report = manualResult || selected?.verification;

  return (
    <div className="verification-layout">
      <Card title="选择策略执行" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新</button>}>
        <div className="field"><label>执行记录</label><select value={selectedId || ''} onChange={(e) => setSelectedId(e.target.value)}>{executionList.map((e) => <option key={e.execution_id} value={e.execution_id}>{executionLabel(e)}</option>)}</select></div>
        <div className="button-row action-group">
          <button type="button" className="primary" onClick={verifySelected}><ClipboardCheck size={16} />验证</button>
          <button type="button" onClick={deploySelected}><Play size={16} />下发</button>
          <details className="more-actions">
            <summary>更多操作</summary>
            <div>
              <button type="button" onClick={autoFix}><Wand2 size={16} />自动修复</button>
              <button type="button" onClick={createApproval}><ShieldCheck size={16} />创建审批</button>
              <button type="button" onClick={showRollbackPlan}><ClipboardCheck size={16} />回滚计划</button>
              <button type="button" onClick={rollbackSelected}><RotateCcw size={16} />原子回滚</button>
              <button type="button" onClick={() => copyText(selected?.policy_set, setToast)}><Copy size={16} />复制策略</button>
            </div>
          </details>
        </div>
        {selected?.policy_set ? <PolicyTable policySet={selected.policy_set} /> : <EmptyState title="没有策略集" text="先提交一次意图。" icon={ShieldCheck} />}
      </Card>

      <Card title="验证摘要">
        {report ? <VerificationSummary report={report} /> : <EmptyState title="暂无验证结果" text="点击“立即验证”后会出现可读结果。" icon={ClipboardCheck} />}
        <IssueList issues={issues} />
      </Card>

      <Card title="自定义配置验证" action={<button type="button" className="primary" onClick={validateCustom}><Play size={14} />验证 JSON</button>}>
        <p className="muted">粘贴局部配置即可验证。</p>
        <textarea value={customJson} onChange={(e) => setCustomJson(e.target.value)} placeholder='{"models":{},"agents":{},"rules":{}}' />
      </Card>
    </div>
  );
}

function PolicyTable({ policySet }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>类型</th><th>名称</th><th>动作</th><th>优先级</th><th>命令</th></tr></thead>
        <tbody>
          {(policySet.policies || []).map((p) => (
            <tr key={p.id}>
              <td><span className="tag">{p.type}</span></td>
              <td>{p.name}</td>
              <td>{p.action}</td>
              <td>{p.priority}</td>
              <td>{(p.commands || []).slice(0, 2).join(' / ') || '--'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VerificationSummary({ report }) {
  const items = [
    ['验证结论', report.passed ? '通过' : '未通过', report.passed ? 'ok' : 'warn'],
    ['可达性', report.reachable ? '可达' : '不可达', report.reachable ? 'ok' : 'error'],
    ['SLA 可行性', report.sla_feasible ? '可行' : '不可行', report.sla_feasible ? 'ok' : 'warn'],
    ['安全检查', report.security_passed ? '通过' : '阻断', report.security_passed ? 'ok' : 'error'],
    ['回滚计划', report.rollback_ready ? '就绪' : '缺失', report.rollback_ready ? 'ok' : 'warn'],
    ['置信度', `${Math.round((report.sla_confidence || 0) * 100)}%`, 'neutral'],
  ];
  return <div className="summary-grid">{items.map(([k, v, tone]) => <div key={k} className={tone}><small>{k}</small><b>{v}</b></div>)}</div>;
}

function IssueList({ issues }) {
  if (!issues?.length) return <InlineSuccess text="没有发现冲突或阻断项。" />;
  return (
    <div className="issue-list">
      {issues.map((issue, index) => (
        <div key={`${issue.code}-${index}`} className={`issue-row ${issue.severity}`}>
          {issue.severity === 'error' ? <XCircle size={18} /> : <AlertTriangle size={18} />}
          <div><b>{issueCodeLabels[issue.code] || issue.code}</b><span>{issue.message}</span></div>
          {issue.auto_fixable && <em>可自动修复</em>}
        </div>
      ))}
    </div>
  );
}

function WorkflowPage({ setToast }) {
  const { data: workflows, reload, setData } = useApi('/api/config/workflows', []);
  const { data: graph } = useApi('/api/langgraph/graph', null);
  const [selectedId, setSelectedId] = useState('default');
  const [intentText, setIntentText] = useState(sampleIntents[0]);
  const [draft, setDraft] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const list = normalizeList(workflows);
  const selected = list.find((w) => w.id === selectedId) || list[0];

  useEffect(() => {
    if (selected) {
      setSelectedId(selected.id);
      setDraft({ ...selected, nodesText: (selected.graph?.nodes || []).join('\n'), edgesText: (selected.graph?.edges || []).map((e) => Array.isArray(e) ? e.join(' -> ') : `${e.source || e[0]} -> ${e.target || e[1]}`).join('\n') });
    }
  }, [selected?.id]);

  const saveWorkflow = async () => {
    const nodes = (draft.nodesText || '').split('\n').map((x) => x.trim()).filter(Boolean);
    const edges = (draft.edgesText || '').split('\n').map((line) => line.split('->').map((x) => x.trim()).filter(Boolean)).filter((e) => e.length === 2);
    const payload = { id: draft.id || 'custom', name: draft.name || '自定义工作流', enabled: draft.enabled !== false, graph: { nodes, edges } };
    try {
      const saved = await request('/api/config/workflows', { method: 'POST', body: payload });
      setData((prev) => [...normalizeList(prev).filter((w) => w.id !== saved.id), saved]);
      toastMessage(setToast, 'success', '工作流已保存');
    } catch (err) {
      toastMessage(setToast, 'error', `保存失败：${err.message}`);
    }
  };

  const runWorkflow = async (requireApproval = false) => {
    try {
      const data = await request(`/api/langgraph/run?require_approval=${requireApproval ? 'true' : 'false'}`, { method: 'POST', body: { workflow_id: selectedId, intent_text: intentText, dry_run: !requireApproval } });
      setRunResult(data);
      toastMessage(setToast, data.interrupts?.length ? 'warn' : 'success', data.interrupts?.length ? '工作流已暂停等待审批' : '工作流运行完成');
    } catch (err) {
      toastMessage(setToast, 'error', `运行失败：${err.message}`);
    }
  };

  const resumeInterrupt = async (interruptId, decision) => {
    try {
      const data = await request(`/api/langgraph/resume/${interruptId}`, { method: 'POST', body: { decision } });
      toastMessage(setToast, data.ok ? 'success' : 'warn', data.ok ? '已恢复执行' : '恢复失败');
      setRunResult((prev) => ({ ...prev, resume: data }));
    } catch (err) {
      toastMessage(setToast, 'error', `恢复失败：${err.message}`);
    }
  };

  return (
    <div className="workflow-layout">
      <Card title="工作流画布" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新</button>}>
        <div className="field"><label>选择工作流</label><select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>{list.map((w) => <option key={w.id} value={w.id}>{w.name || w.id}</option>)}</select></div>
        <WorkflowCanvas workflow={selected} graph={graph} />
      </Card>
      <Card title="工作流编辑" action={<button type="button" className="primary" onClick={saveWorkflow}><Save size={14} />保存工作流</button>}>
        {draft ? <div className="form-grid">
          <div className="field"><label>ID</label><input value={draft.id || ''} onChange={(e) => setDraft({ ...draft, id: e.target.value })} /></div>
          <div className="field"><label>名称</label><input value={draft.name || ''} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
          <label className="checkline"><input type="checkbox" checked={draft.enabled !== false} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用工作流</label>
          <div className="field span-2"><label>节点，每行一个</label><textarea value={draft.nodesText || ''} onChange={(e) => setDraft({ ...draft, nodesText: e.target.value })} /></div>
          <div className="field span-2"><label>连线，格式 A -&gt; B</label><textarea value={draft.edgesText || ''} onChange={(e) => setDraft({ ...draft, edgesText: e.target.value })} /></div>
        </div> : <EmptyState title="没有工作流" text="接口尚未返回工作流配置。" icon={Workflow} />}
      </Card>
      <Card title="运行与审批">
        <div className="field"><label>测试意图</label><textarea value={intentText} onChange={(e) => setIntentText(e.target.value)} /></div>
        <div className="button-row">
          <button type="button" onClick={() => runWorkflow(false)}><Play size={16} />试运行</button>
          <button type="button" onClick={() => runWorkflow(true)}><ShieldCheck size={16} />需要审批运行</button>
          <button type="button" onClick={() => copyText(runResult, setToast)}><Copy size={16} />复制结果</button>
        </div>
        {runResult?.interrupts?.map((it) => <div className="approval-row" key={it.interrupt_id}><span>{it.reason || it.interrupt_id}</span><button type="button" onClick={() => resumeInterrupt(it.interrupt_id, 'approved')}><Check size={14} />批准</button><button type="button" onClick={() => resumeInterrupt(it.interrupt_id, 'rejected')}><X size={14} />拒绝</button></div>)}
        {runResult && <JsonBlock data={runResult} setToast={setToast} />}
      </Card>
    </div>
  );
}

function WorkflowCanvas({ workflow, graph }) {
  const nodes = workflow?.graph?.nodes || graph?.nodes || [];
  const edges = workflow?.graph?.edges || graph?.edges || [];
  return (
    <div className="workflow-canvas">
      {nodes.map((node, index) => (
        <div key={node.id || node} className="workflow-node" style={{ '--i': index }}>
          <span>{index + 1}</span>
          <b>{node.id || node}</b>
          <small>{node.type || 'agent step'}</small>
        </div>
      ))}
      <div className="edge-list">
        {edges.map((edge, index) => {
          const src = Array.isArray(edge) ? edge[0] : edge.source || edge.from;
          const dst = Array.isArray(edge) ? edge[1] : edge.target || edge.to;
          return <span key={index}>{src} → {dst}</span>;
        })}
      </div>
    </div>
  );
}

function Telemetry({ setToast }) {
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState([]);
  const [diagnosis, setDiagnosis] = useState(null);
  const [anomaly, setAnomaly] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [wsEvents, setWsEvents] = useState([]);
  const [wsStatus, setWsStatus] = useState('connecting');
  const [running, setRunning] = useState(true);
  const timer = useRef(null);


  useEffect(() => {
    const wsUrl = API.replace(/^http/, 'ws') + '/ws/events';
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => setWsStatus('connected');
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        setWsEvents((prev) => [payload, ...prev].slice(0, 6));
      } catch (_) {
        setWsEvents((prev) => [{ type: 'raw', data: event.data }, ...prev].slice(0, 6));
      }
    };
    ws.onerror = () => setWsStatus('error');
    ws.onclose = () => setWsStatus((prev) => prev === 'connected' ? 'closed' : prev);
    return () => ws.close();
  }, []);

  const loadAnomaly = async () => {
    try {
      const data = await request('/api/telemetry/anomaly?limit=12');
      setAnomaly(data);
      toastMessage(setToast, data.anomaly ? 'warn' : 'success', data.anomaly ? `滑动窗口异常：${data.reason}` : '滑动窗口未发现异常');
    } catch (err) {
      toastMessage(setToast, 'error', `异常检测失败：${err.message}`);
    }
  };

  const predictSla = async () => {
    try {
      const data = await request('/api/telemetry/predict-sla', { method: 'POST', body: { business: 'video_meeting', description: '前端 SLA 预测', target: { src: 'teacher_terminal', dst: 'meeting_server', traffic_type: 'video' }, sla: { latency_ms: 50, packet_loss: 0.01, bandwidth_mbps: 20 }, constraints: {} } });
      setPrediction(data);
      toastMessage(setToast, data.feasible ? 'success' : 'warn', data.feasible ? 'SLA 历史均值预测可行' : 'SLA 预测不可行');
    } catch (err) {
      toastMessage(setToast, 'error', `SLA 预测失败：${err.message}`);
    }
  };

  const load = async () => {
    try {
      const latest = await request('/api/telemetry/latest');
      setSnapshot(latest);
      setHistory((prev) => [...prev.slice(-29), latest]);
    } catch (err) {
      toastMessage(setToast, 'error', `遥测获取失败：${err.message}`);
      setRunning(false);
    }
  };

  useEffect(() => {
    load();
    timer.current = setInterval(() => running && load(), 1600);
    return () => clearInterval(timer.current);
  }, [running]);

  const fault = async (kind) => {
    try {
      const data = await request('/api/experiment/fault', { method: 'POST', body: { kind } });
      toastMessage(setToast, data.alert ? 'warn' : 'success', `故障注入：${kind}`);
      await load();
    } catch (err) {
      toastMessage(setToast, 'error', `故障注入失败：${err.message}`);
    }
  };

  const diagnose = async () => {
    try {
      const data = await request('/api/telemetry/diagnose', { method: 'POST' });
      setDiagnosis(data);
      toastMessage(setToast, data.type === 'normal' ? 'success' : 'warn', `诊断结果：${data.type}`);
    } catch (err) {
      toastMessage(setToast, 'error', `诊断失败：${err.message}`);
    }
  };

  const heal = async () => {
    try {
      const data = await request('/api/telemetry/heal', { method: 'POST' });
      toastMessage(setToast, data.success ? 'success' : 'warn', data.summary || '自愈完成');
      await load();
    } catch (err) {
      toastMessage(setToast, 'error', `自愈失败：${err.message}`);
    }
  };

  return (
    <div className="telemetry-layout">
      <Card title="实时遥测" action={<button type="button" onClick={() => setRunning((x) => !x)}>{running ? '暂停' : '继续'}</button>}>
        <div className="metrics-grid compact">
          <StatCard label="延迟" value={snapshot?.latency_ms} unit="ms" tone={snapshot?.latency_ms > 50 ? 'warn' : 'ok'} />
          <StatCard label="丢包率" value={snapshot?.packet_loss} tone={snapshot?.packet_loss > 0.01 ? 'warn' : 'ok'} />
          <StatCard label="吞吐" value={snapshot?.throughput_mbps} unit="Mbps" tone="neutral" />
        </div>
        <Sparkline rows={history} field="latency_ms" />
      </Card>
      <Card title="诊断与处置">
        <div className="fault-grid">
          {[
            ['congestion', '链路拥塞'],
            ['link_down', '链路断开'],
            ['guest_spike', '访客突增'],
            ['normal', '恢复正常'],
          ].map(([kind, label]) => <button type="button" key={kind} onClick={() => fault(kind)}><Terminal size={16} />{label}</button>)}
        </div>
        <div className="button-row">
          <button type="button" onClick={diagnose}><Eye size={16} />诊断</button>
          <button type="button" onClick={loadAnomaly}><Activity size={16} />异常检测</button>
          <button type="button" onClick={predictSla}><Gauge size={16} />SLA 预测</button>
          <button type="button" className="primary" onClick={heal}><Wand2 size={16} />执行自愈</button>
        </div>
        {diagnosis && <JsonBlock data={diagnosis} setToast={setToast} />}
        {anomaly && <JsonBlock data={anomaly} setToast={setToast} maxHeight={240} />}
        {prediction && <JsonBlock data={prediction} setToast={setToast} maxHeight={240} />}
      </Card>
      <Card title="实时推送" action={<span className={`pill ${wsStatus === 'connected' ? 'ok' : 'warn'}`}>{wsStatus}</span>}>
        <div className="log-stream">{wsEvents.length ? wsEvents.map((event, index) => <div key={index} className="log-row info"><span className="log-level">WS</span><span className="log-time">{event.type}</span><b>push</b><p>{JSON.stringify(event.data)}</p></div>) : <EmptyState title="等待推送" text="等待后端实时事件。" icon={Radio} />}</div>
      </Card>
      <Card title="原始数据"><details className="raw-details"><summary>查看当前快照</summary><JsonBlock data={snapshot || { message: '等待遥测' }} setToast={setToast} /></details></Card>
    </div>
  );
}

function Sparkline({ rows, field }) {
  const values = rows.map((x) => Number(x[field] || 0));
  const max = Math.max(1, ...values);
  const points = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${100 - (v / max) * 86}`).join(' ');
  return <div className="sparkline"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={points} /></svg></div>;
}

function Logs({ setToast, refreshKey }) {
  const [source, setSource] = useState('');
  const [level, setLevel] = useState('');
  const [keyword, setKeyword] = useState('');
  const path = `/api/logs?limit=120${source ? `&source=${encodeURIComponent(source)}` : ''}${level ? `&level=${encodeURIComponent(level)}` : ''}`;
  const { data, reload, error } = useApi(path, [], refreshKey);
  const rows = normalizeList(data).filter((row) => JSON.stringify(row).toLowerCase().includes(keyword.toLowerCase()));
  const sources = [...new Set(normalizeList(data).map((r) => r.source).filter(Boolean))];

  return (
    <div className="logs-layout">
      <Card title="日志筛选" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新</button>}>
        <div className="form-grid compact">
          <SearchBox value={keyword} onChange={setKeyword} placeholder="搜索消息、执行ID、数据" />
          <div className="field"><label>来源</label><select value={source} onChange={(e) => setSource(e.target.value)}><option value="">全部</option>{sources.map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
          <div className="field"><label>等级</label><select value={level} onChange={(e) => setLevel(e.target.value)}><option value="">全部</option><option value="info">info</option><option value="warn">warn</option><option value="error">error</option></select></div>
        </div>
        <div className="button-row">
          <button type="button" onClick={() => downloadText('netmind-logs.json', JSON.stringify(rows, null, 2))}><Download size={16} />导出</button>
          <button type="button" onClick={() => copyText(rows, setToast)}><Copy size={16} />复制结果</button>
        </div>
        {error && <InlineError text={error} />}
      </Card>
      <Card title="日志列表">
        <div className="log-stream">
          {rows.length ? rows.slice().reverse().map((row, index) => <LogRow key={`${row.ts}-${index}`} row={row} keyword={keyword} />) : <EmptyState title="没有匹配日志" text="调整筛选条件。" icon={ScrollText} />}
        </div>
      </Card>
    </div>
  );
}

function LogRow({ row, keyword }) {
  const msg = row.message || JSON.stringify(row.data || row);
  const highlight = (text) => {
    if (!keyword) return text;
    const i = String(text).toLowerCase().indexOf(keyword.toLowerCase());
    if (i < 0) return text;
    return <>{text.slice(0, i)}<mark>{text.slice(i, i + keyword.length)}</mark>{text.slice(i + keyword.length)}</>;
  };
  return (
    <div className={`log-row ${row.level || 'info'}`}>
      <span className="log-level">{row.level || 'info'}</span>
      <span className="log-meta"><em>{row.ts ? new Date(row.ts).toLocaleTimeString() : '--'}</em><b>{row.source || 'system'}</b></span>
      <p>{highlight(msg)}</p>
    </div>
  );
}

function Reports({ setToast }) {
  const { data: executions, reload } = useApi('/api/executions', []);
  const list = normalizeList(executions);
  const [selectedId, setSelectedId] = useState('');
  const selected = list.find((e) => e.execution_id === selectedId) || list.at(-1);
  const [includeLogs, setIncludeLogs] = useState(true);
  const [includeRaw, setIncludeRaw] = useState(false);
  const [report, setReport] = useState('');

  useEffect(() => { if (selected) setSelectedId(selected.execution_id); }, [selected?.execution_id]);

  const generate = async () => {
    if (!selected?.execution_id) return toastMessage(setToast, 'warn', '请选择执行记录');
    try {
      const data = await request('/api/report/generate/options', { method: 'POST', body: { execution_id: selected.execution_id, include_logs: includeLogs, include_raw_json: includeRaw } });
      setReport(data);
      toastMessage(setToast, 'success', '报告已生成');
    } catch (err) {
      try {
        const data = await request('/api/report/generate', { method: 'POST', body: { execution_id: selected.execution_id } });
        setReport(data);
        toastMessage(setToast, 'success', '报告已生成');
      } catch (inner) {
        toastMessage(setToast, 'error', `报告生成失败：${inner.message}`);
      }
    }
  };

  return (
    <div className="reports-layout">
      <Card title="报告生成器" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新执行</button>}>
        <div className="field"><label>执行记录</label><select value={selectedId || ''} onChange={(e) => setSelectedId(e.target.value)}>{list.map((e) => <option key={e.execution_id} value={e.execution_id}>{executionLabel(e)}</option>)}</select></div>
        <label className="checkline"><input type="checkbox" checked={includeLogs} onChange={(e) => setIncludeLogs(e.target.checked)} />包含日志</label>
        <label className="checkline"><input type="checkbox" checked={includeRaw} onChange={(e) => setIncludeRaw(e.target.checked)} />包含原始 JSON</label>
        <div className="button-row">
          <button type="button" className="primary" onClick={generate}><FileText size={16} />生成 Markdown</button>
          <button type="button" onClick={() => selected?.execution_id && window.open(`${API}/api/report/${selected.execution_id}/rich.html`, '_blank')}><Eye size={16} />打开 HTML</button>
          <button type="button" onClick={() => selected?.execution_id && window.open(`${API}/api/report/${selected.execution_id}/rich.pdf`, '_blank')}><Download size={16} />下载 PDF</button>
          <button type="button" onClick={() => copyText(report, setToast)}><Copy size={16} />复制报告</button>
        </div>
      </Card>
      <Card title="报告预览"><JsonBlock data={report || '尚未生成报告'} setToast={setToast} maxHeight={620} /></Card>
    </div>
  );
}


function FeatureAcceptance({ setPage, setToast }) {
  const [acceptance, setAcceptance] = useState(null);
  const [loading, setLoading] = useState(false);
  const capabilityGroups = [
    { title: '意图闭环', desc: '自然语言解析、DSL 编译、策略规划', page: 'intent', icon: Radio },
    { title: '策略安全', desc: '冲突检测、路径验证、SLA 预测、下发与回滚', page: 'verification', icon: ShieldCheck },
    { title: '网络遥测', desc: '实时采集、推送、异常检测', page: 'telemetry', icon: Activity },
    { title: '诊断处置', desc: '故障诊断、自愈执行、报告生成', page: 'telemetry', icon: Wand2 },
    { title: '流程编排', desc: 'Agent 任务传递与审批运行', page: 'workflow', icon: Workflow },
  ];

  const runAcceptance = async () => {
    setLoading(true);
    try {
      const data = await request('/api/readiness');
      const total = 3;
      const implemented = total - (data.missing ? data.missing.length : 0);
      setAcceptance({ all_passed: !!data.ready, implemented, total });
      toastMessage(setToast, data.ready ? 'success' : 'warn', data.ready ? '运行时就绪：规则 / Agent / 工具齐备' : `缺少: ${(data.missing || []).join(', ')}`);
    } catch (err) {
      toastMessage(setToast, 'error', `自检失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };
  const submitDemo = async () => {
    try {
      await request('/api/intent/submit', { method: 'POST', body: { text: sampleIntents[0], dry_run: true } });
      toastMessage(setToast, 'success', '演示执行已创建');
      setPage('agents');
    } catch (err) {
      toastMessage(setToast, 'error', `演示执行失败：${err.message}`);
    }
  };
  return (
    <div className="stack gap-xl">
      <div className="hero-dashboard compact-hero feature-hero">
        <div>
          <span className="eyebrow"><ClipboardCheck size={14} />系统自检</span>
          <h2>核心能力状态一眼看懂。</h2>
          <p>用于交付前快速确认系统链路是否正常。</p>
          <div className="button-row">
            <button type="button" className="primary" onClick={runAcceptance} disabled={loading}><Play size={16} />开始自检</button>
            <button type="button" onClick={submitDemo}><Radio size={16} />生成演示</button>
            <button type="button" onClick={() => copyText(acceptance, setToast)} disabled={!acceptance}><Copy size={16} />复制结果</button>
          </div>
        </div>
        <HealthRing score={acceptance ? Math.round((acceptance.implemented / Math.max(acceptance.total, 1)) * 100) : 100} />
      </div>

      <div className="capability-grid">
        {capabilityGroups.map(({ title, desc, page, icon: Icon }) => (
          <button key={title} type="button" className="capability-card" onClick={() => setPage(page)}>
            <Icon size={18} />
            <b>{title}</b>
            <span>{desc}</span>
            <em>{acceptance ? (acceptance.all_passed ? '正常' : '需关注') : '待自检'}</em>
          </button>
        ))}
      </div>

      {acceptance && (
        <Card title="自检结果">
          <div className="summary-grid compact-summary">
            <div className={acceptance.all_passed ? 'ok' : 'warn'}><small>结果</small><b>{acceptance.all_passed ? '通过' : '需关注'}</b></div>
            <div><small>覆盖能力</small><b>{acceptance.implemented}/{acceptance.total}</b></div>
          </div>
        </Card>
      )}
    </div>
  );
}

function ConfigCenter({ settings, updateSettings, setToast }) {
  const tabs = [
    ['appearance', '主题字体', Palette],
    ['models', '模型', Sparkles],
    ['agents', '智能体', Bot],
    ['rules', '规则', ShieldCheck],
    ['tools', '工具', Terminal],
    ['workflows', '工作流', Workflow],
    ['security', '安全', KeyRound],
    ['import', '导入导出', Database],
  ];
  const [tab, setTab] = useState('appearance');
  const [query, setQuery] = useState('');

  return (
    <div className="config-center">
      <Card className="config-nav" title="配置导航">
        <SearchBox value={query} onChange={setQuery} placeholder="搜索配置项…" />
        <div className="tab-list">
          {tabs.map(([id, label, Icon]) => <button key={id} type="button" onClick={() => setTab(id)} className={tab === id ? 'active' : ''}><Icon size={16} />{label}</button>)}
        </div>
      </Card>
      <div className="config-content">
        {tab === 'appearance' && <AppearanceSettings settings={settings} updateSettings={updateSettings} setToast={setToast} />}
        {tab === 'models' && <ModelsConfig query={query} setToast={setToast} />}
        {tab === 'agents' && <AgentsConfig query={query} setToast={setToast} />}
        {tab === 'rules' && <RulesConfig query={query} setToast={setToast} />}
        {tab === 'tools' && <ToolsConfig query={query} setToast={setToast} />}
        {tab === 'workflows' && <WorkflowsConfig query={query} setToast={setToast} />}
        {tab === 'security' && <SecurityConfig setToast={setToast} />}
        {tab === 'import' && <ImportExportConfig setToast={setToast} />}
      </div>
    </div>
  );
}

function AppearanceSettings({ settings, updateSettings, setToast }) {
  const [themeDraft, setThemeDraft] = useState(null);
  const { data: backendTheme, reload } = useApi('/api/config/theme', null);
  const { data: fontConfig } = useApi('/api/config/fonts', null);

  useEffect(() => { if (backendTheme) setThemeDraft(backendTheme); }, [backendTheme?.primary, backendTheme?.background]);

  const saveBackendTheme = async () => {
    const preset = themePresets[settings.theme] || themePresets.aurora;
    const payload = themeDraft || { primary: preset.primary, background: preset.background, card: preset.card, radius: 14, font: fontChoices.find((f) => f.id === settings.font)?.label || 'system' };
    try {
      await request('/api/config/theme', { method: 'POST', body: payload });
      await request('/api/config/fonts', { method: 'PUT', body: { font_family: fontChoices.find((f) => f.id === settings.font)?.family || fontChoices[0].family, font_scale: settings.fontSize } });
      toastMessage(setToast, 'success', '主题和字体已保存到后端');
      reload();
    } catch (err) {
      toastMessage(setToast, 'error', `保存失败：${err.message}`);
    }
  };

  return (
    <div className="appearance-grid">
      <Card title="主题选择" action={<button type="button" className="primary" onClick={saveBackendTheme}><Save size={14} />保存到后端</button>}>
        <div className="theme-grid">
          {Object.entries(themePresets).map(([id, preset]) => <button type="button" key={id} className={`theme-choice ${settings.theme === id ? 'active' : ''}`} onClick={() => updateSettings({ theme: id })} style={{ '--swatch': preset.primary, '--swatch-bg': preset.background }}><span /><b>{preset.name}</b></button>)}
        </div>
        <div className="form-grid">
          <div className="field"><label>主色</label><input type="color" value={themeDraft?.primary || themePresets[settings.theme].primary} onChange={(e) => setThemeDraft({ ...(themeDraft || backendTheme || {}), primary: e.target.value })} /></div>
          <div className="field"><label>背景</label><input type="color" value={themeDraft?.background || themePresets[settings.theme].background} onChange={(e) => setThemeDraft({ ...(themeDraft || backendTheme || {}), background: e.target.value })} /></div>
          <div className="field"><label>卡片</label><input type="color" value={themeDraft?.card || themePresets[settings.theme].card} onChange={(e) => setThemeDraft({ ...(themeDraft || backendTheme || {}), card: e.target.value })} /></div>
          <div className="field"><label>圆角</label><input type="number" min="4" max="28" value={themeDraft?.radius ?? 14} onChange={(e) => setThemeDraft({ ...(themeDraft || backendTheme || {}), radius: Number(e.target.value) })} /></div>
        </div>
      </Card>
      <Card title="字体与字号">
        <div className="font-grid">
          {fontChoices.map((font) => <button type="button" key={font.id} className={settings.font === font.id ? 'active' : ''} onClick={() => updateSettings({ font: font.id })} style={{ fontFamily: font.family }}><Type size={16} />{font.label}</button>)}
        </div>
        <div className="field"><label>全局字号：{Math.round(settings.fontSize * 100)}%</label><input type="range" min="0.9" max="1.25" step="0.05" value={settings.fontSize} onChange={(e) => updateSettings({ fontSize: Number(e.target.value) })} /></div>
        <div className="field"><label>界面密度</label><select value={settings.density} onChange={(e) => updateSettings({ density: e.target.value })}><option value="comfortable">舒展</option><option value="compact">紧凑</option></select></div>
        <JsonBlock data={fontConfig || { message: '字体后端配置加载中' }} setToast={setToast} />
      </Card>
    </div>
  );
}

function ModelsConfig({ query, setToast }) {
  const { data, setData, reload } = useApi('/api/config/models', []);
  const { data: presetData } = useApi('/api/config/models/presets', fallbackModelPresets);
  const presets = normalizeList(presetData).length ? normalizeList(presetData) : fallbackModelPresets;
  const presetById = useMemo(() => Object.fromEntries(presets.map((p) => [p.id, p])), [JSON.stringify(presets)]);
  const rows = normalizeList(data).filter((m) => JSON.stringify(m).toLowerCase().includes(query.toLowerCase()));

  const emptyDraft = (provider = 'deepseek') => {
    const preset = presetById[provider] || fallbackModelPresets[0];
    const suffix = Math.random().toString(36).slice(2, 6);
    return {
      id: `${provider}-${suffix}`,
      name: `${preset.name} 配置`,
      provider,
      base_url: preset.base_url || '',
      model_id: preset.default_model || preset.models?.[0] || '',
      api_style: preset.api_style || 'openai-compatible',
      api_key: '',
      max_tokens: 4096,
      temperature: 0.7,
      top_p: 1,
      thinking_mode: false,
      context_window: preset.context_window || '',
      enabled: true,
      online: false,
      api_key_set: false,
    };
  };

  const [draft, setDraft] = useState(() => emptyDraft('deepseek'));
  const selectedPreset = presetById[draft.provider] || presetById.custom || fallbackModelPresets.at(-1);
  const modelOptions = selectedPreset?.models || [];

  const applyProvider = (provider) => {
    const preset = presetById[provider] || presetById.custom || {};
    setDraft((prev) => ({
      ...prev,
      provider,
      id: prev.id && !prev.id.startsWith(prev.provider || '') ? prev.id : `${provider}-${Math.random().toString(36).slice(2, 6)}`,
      name: prev.name && !prev.name.includes('配置') ? prev.name : `${preset.name || '自定义'} 配置`,
      base_url: preset.base_url ?? prev.base_url,
      model_id: preset.default_model || preset.models?.[0] || prev.model_id || '',
      api_style: preset.api_style || 'openai-compatible',
      context_window: preset.context_window || '',
      thinking_mode: preset.supports_thinking ? prev.thinking_mode : false,
    }));
  };

  const edit = (row) => setDraft({
    ...emptyDraft(row.provider || 'custom'),
    ...row,
    api_key: '',
    temperature: row.temperature ?? 0.7,
    top_p: row.top_p ?? 1,
    max_tokens: row.max_tokens ?? 4096,
    thinking_mode: Boolean(row.thinking_mode),
  });

  const save = async () => {
    if (!draft.id || !draft.name || !draft.base_url || !draft.model_id) {
      toastMessage(setToast, 'warn', '请填写配置名称、Base URL 和模型 ID');
      return;
    }
    if (!draft.api_key && !draft.api_key_set && draft.provider !== 'ollama' && draft.provider !== 'mock') {
      toastMessage(setToast, 'warn', '请填写 API Key，已保存的配置可留空');
      return;
    }
    try {
      const payload = {
        ...draft,
        temperature: Number(draft.temperature),
        top_p: Number(draft.top_p),
        max_tokens: Number(draft.max_tokens),
        thinking_mode: Boolean(draft.thinking_mode),
        enabled: Boolean(draft.enabled),
      };
      const saved = await request('/api/config/models', { method: 'POST', body: payload });
      setData((prev) => [...normalizeList(prev).filter((m) => m.id !== saved.id), saved]);
      setDraft({ ...saved, api_key: '' });
      toastMessage(setToast, 'success', '模型配置已保存');
    } catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };

  const test = async (id) => {
    try {
      const res = await request('/api/config/models/test', { method: 'POST', body: { model_id: id } });
      toastMessage(setToast, res.ok ? 'success' : 'warn', res.ok ? '模型连接成功' : `连接失败：${res.error || res.status_code || '请检查配置'}`);
      if (res.model) reload();
    } catch (err) { toastMessage(setToast, 'error', `测试失败：${err.message}`); }
  };

  const remove = async (id) => {
    try {
      await request(`/api/config/models/${encodeURIComponent(id)}`, { method: 'DELETE' });
      setData((prev) => normalizeList(prev).filter((m) => m.id !== id));
      if (draft.id === id) setDraft(emptyDraft('deepseek'));
      toastMessage(setToast, 'success', '模型配置已删除');
    } catch (err) { toastMessage(setToast, 'error', `删除失败：${err.message}`); }
  };

  return (
    <div className="model-config-layout">
      <Card title="模型配置" action={<button type="button" onClick={() => setDraft(emptyDraft('deepseek'))}><Plus size={14} />新建</button>}>
        <div className="model-list">
          {rows.map((m) => (
            <button type="button" key={m.id} onClick={() => edit(m)} className={draft.id === m.id ? 'active' : ''}>
              <Sparkles size={18} />
              <div>
                <b>{m.name}</b>
                <small>{m.model_id} · {m.api_key_set ? '已配置 Key' : m.provider === 'ollama' ? '本地连接' : '未配置 Key'}</small>
              </div>
              <span className={m.online ? 'pill ok' : m.enabled ? 'pill warn' : 'pill'}>{m.online ? '在线' : m.enabled ? '待测' : '停用'}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card title="接入参数" action={<button type="button" className="primary" onClick={save}><Save size={14} />保存配置</button>}>
        <div className="model-form-grid">
          <div className="field"><label>厂商</label><select value={draft.provider} onChange={(e) => applyProvider(e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.region} · {p.name}</option>)}</select></div>
          <div className="field"><label>配置名称</label><input value={draft.name || ''} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="生产 DeepSeek V4" /></div>
          <div className="field"><label>配置 ID</label><input value={draft.id || ''} onChange={(e) => setDraft({ ...draft, id: e.target.value })} placeholder="deepseek-prod" /></div>
          <div className="field"><label>API Key</label><input type="password" autoComplete="new-password" value={draft.api_key || ''} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} placeholder={draft.api_key_set ? '●●●●●●●●（留空则保持原 Key）' : draft.provider === 'ollama' ? '本地 Ollama 可留空' : '填写 API Key'} /></div>
          <div className="field span-2"><label>Base URL</label><input value={draft.base_url || ''} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} placeholder="https://api.example.com/v1" /></div>
          <div className="field span-2"><label>模型 ID</label><input list="model-id-options" value={draft.model_id || ''} onChange={(e) => setDraft({ ...draft, model_id: e.target.value })} placeholder="选择或手动输入模型 ID" /><datalist id="model-id-options">{modelOptions.map((m) => <option key={m} value={m} />)}</datalist></div>
        </div>

        <details className="advanced-panel" open>
          <summary><SlidersHorizontal size={15} />模型参数</summary>
          <div className="model-form-grid compact-controls">
            <div className="field"><label>最大 Token</label><input type="number" min="1" max="262144" value={draft.max_tokens ?? 4096} onChange={(e) => setDraft({ ...draft, max_tokens: Number(e.target.value) })} /></div>
            <div className="field"><label>上下文窗口</label><input value={draft.context_window || ''} onChange={(e) => setDraft({ ...draft, context_window: e.target.value })} placeholder="如 128K" /></div>
            <div className="field"><label>温度：{Number(draft.temperature ?? 0.7).toFixed(1)}</label><input type="range" min="0" max="2" step="0.1" value={draft.temperature ?? 0.7} onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })} /></div>
            <div className="field"><label>Top-P：{Number(draft.top_p ?? 1).toFixed(2)}</label><input type="range" min="0" max="1" step="0.05" value={draft.top_p ?? 1} onChange={(e) => setDraft({ ...draft, top_p: Number(e.target.value) })} /></div>
            <label className="checkline"><input type="checkbox" checked={Boolean(draft.thinking_mode)} disabled={!selectedPreset?.supports_thinking} onChange={(e) => setDraft({ ...draft, thinking_mode: e.target.checked })} />思考模式{!selectedPreset?.supports_thinking ? '（当前厂商不支持）' : ''}</label>
            <label className="checkline"><input type="checkbox" checked={draft.enabled !== false} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用该配置</label>
          </div>
        </details>

        <div className="button-row">
          <button type="button" onClick={() => test(draft.id)}><Play size={16} />测试连接</button>
          <button type="button" onClick={() => copyText({ ...draft, api_key: draft.api_key ? '●●●●●●●●' : undefined }, setToast)}><Copy size={16} />复制参数</button>
          {draft.id && draft.id !== 'mock' && <button type="button" className="ghost" onClick={() => remove(draft.id)}><X size={16} />删除</button>}
        </div>
      </Card>
    </div>
  );
}

function AgentsConfig({ query, setToast }) {
  const { data, setData, reload } = useApi('/api/config/agents', []);
  const { data: modelsData } = useApi('/api/config/models', []);
  const modelOptions = normalizeList(modelsData).map((m) => m.id);
  const rows = normalizeList(data).filter((m) => JSON.stringify(m).toLowerCase().includes(query.toLowerCase()));
  const [draft, setDraft] = useState({ name: 'CustomAgent', level: 'secondary', model_id: 'mock', allowed_tools_text: '', prompt: '' });
  const edit = (row) => setDraft({ ...row, allowed_tools_text: (row.allowed_tools || []).join(', ') });
  const save = async () => {
    try {
      const saved = await request('/api/config/agents', { method: 'POST', body: { ...draft, allowed_tools: (draft.allowed_tools_text || '').split(',').map((x) => x.trim()).filter(Boolean) } });
      setData((prev) => [...normalizeList(prev).filter((m) => m.name !== saved.name), saved]);
      toastMessage(setToast, 'success', '智能体已保存');
    } catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };
  return <EditableList setToast={setToast} title="智能体" rows={rows} idKey="name" onEdit={edit} onRefresh={reload} draft={draft} setDraft={setDraft} onSave={save} fields={[['name','名称'],['level','层级','select',['primary','secondary','tertiary']],['model_id','绑定模型','select',modelOptions.length ? modelOptions : ['mock']],['allowed_tools_text','工具，逗号分隔'],['prompt','提示词','textarea']]} />;
}

function RulesConfig({ query, setToast }) {
  const { data, setData, reload } = useApi('/api/config/rules', []);
  const rows = normalizeList(data).filter((m) => JSON.stringify(m).toLowerCase().includes(query.toLowerCase()));
  const [draft, setDraft] = useState({ name: 'custom_rule', description: '自定义规则', priority: 10, enabled: true, match_business: 'video_meeting', action_template_text: '{}' });
  const edit = (row) => setDraft({ ...row, action_template_text: JSON.stringify(row.action_template || {}, null, 2) });
  const save = async () => {
    try {
      const payload = { ...draft, priority: Number(draft.priority), action_template: JSON.parse(draft.action_template_text || '{}') };
      const saved = await request('/api/config/rules', { method: 'POST', body: payload });
      setData((prev) => [...normalizeList(prev).filter((m) => m.name !== saved.name), saved]);
      toastMessage(setToast, 'success', '规则已保存');
    } catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };
  const testRule = async () => {
    try { const intent = await request('/api/intent/parse', { method: 'POST', body: { text: sampleIntents[0] } }); const res = await request('/api/config/rules/test', { method: 'POST', body: intent }); toastMessage(setToast, 'success', `匹配 ${res.matches?.length || 0} 条规则`); }
    catch (err) { toastMessage(setToast, 'error', `规则测试失败：${err.message}`); }
  };
  return <EditableList setToast={setToast} title="规则" rows={rows} idKey="name" onEdit={edit} onRefresh={reload} draft={draft} setDraft={setDraft} onSave={save} extraAction={<button type="button" onClick={testRule}><Play size={14} />测试规则</button>} fields={[['name','名称'],['description','说明'],['priority','优先级','number'],['match_business','匹配业务'],['action_template_text','动作模板 JSON','textarea']]} />;
}

function ToolsConfig({ query, setToast }) {
  const { data, setData, reload } = useApi('/api/config/tools', []);
  const rows = normalizeList(data).filter((m) => JSON.stringify(m).toLowerCase().includes(query.toLowerCase())).map((m) => ({ ...m, display_name: displayToolName(m.name), description: (m.description || '').replace(/免费/g, '').replace(/无需外部 API/g, '适用于本地验证') }));
  const [draft, setDraft] = useState({ name: 'custom_tool', description: '自定义工具', parameters_schema_text: '{}', enabled: true });
  const edit = (row) => setDraft({ ...row, parameters_schema_text: JSON.stringify(row.parameters_schema || {}, null, 2) });
  const save = async () => {
    try {
      const payload = { ...draft, parameters_schema: JSON.parse(draft.parameters_schema_text || '{}') };
      const saved = await request('/api/config/tools', { method: 'POST', body: payload });
      setData((prev) => [...normalizeList(prev).filter((m) => m.name !== saved.name), saved]);
      toastMessage(setToast, 'success', '工具已保存');
    } catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };
  const callTool = async () => {
    try { const res = await request('/api/mcp/call_tool', { method: 'POST', body: { tool_name: draft.name, arguments: {}, dry_run: true } }); toastMessage(setToast, res.result?.ok ? 'success' : 'warn', '工具试调用完成'); }
    catch (err) { toastMessage(setToast, 'error', `调用失败：${err.message}`); }
  };
  return <EditableList setToast={setToast} title="工具" rows={rows} idKey="name" onEdit={edit} onRefresh={reload} draft={draft} setDraft={setDraft} onSave={save} extraAction={<button type="button" onClick={callTool}><Play size={14} />试调用</button>} fields={[['name','名称'],['description','说明'],['parameters_schema_text','参数 Schema JSON','textarea']]} />;
}

function WorkflowsConfig({ query, setToast }) {
  const { data, setData, reload } = useApi('/api/config/workflows', []);
  const rows = normalizeList(data).filter((m) => JSON.stringify(m).toLowerCase().includes(query.toLowerCase()));
  const [draft, setDraft] = useState({ id: 'custom', name: '自定义工作流', enabled: true, nodesText: 'OrchestratorAgent\nIntentAgent\nPlannerAgent\nVerifierAgent', edgesText: 'OrchestratorAgent -> IntentAgent\nIntentAgent -> PlannerAgent\nPlannerAgent -> VerifierAgent' });
  const edit = (row) => setDraft({ ...row, nodesText: (row.graph?.nodes || []).join('\n'), edgesText: (row.graph?.edges || []).map((e) => Array.isArray(e) ? e.join(' -> ') : `${e.source} -> ${e.target}`).join('\n') });
  const save = async () => {
    try {
      const nodes = (draft.nodesText || '').split('\n').map((x) => x.trim()).filter(Boolean);
      const edges = (draft.edgesText || '').split('\n').map((x) => x.split('->').map((s) => s.trim())).filter((x) => x.length === 2);
      const saved = await request('/api/config/workflows', { method: 'POST', body: { id: draft.id, name: draft.name, enabled: draft.enabled, graph: { nodes, edges } } });
      setData((prev) => [...normalizeList(prev).filter((m) => m.id !== saved.id), saved]);
      toastMessage(setToast, 'success', '工作流已保存');
    } catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };
  return <EditableList setToast={setToast} title="工作流" rows={rows} idKey="id" onEdit={edit} onRefresh={reload} draft={draft} setDraft={setDraft} onSave={save} fields={[['id','ID'],['name','名称'],['nodesText','节点，每行一个','textarea'],['edgesText','连线 A -> B','textarea']]} />;
}

function SecurityConfig({ setToast }) {
  const { data, setData, reload } = useApi('/api/config/security', null);
  const [draft, setDraft] = useState({});
  const [command, setCommand] = useState('ping -c 1 10.0.0.1');
  const [check, setCheck] = useState(null);
  useEffect(() => { if (data) setDraft({ ...data, allowlistText: (data.allowlist || []).join(', '), denyText: (data.deny_keywords || []).join(', '), approvalText: (data.approval_required || []).join(', ') }); }, [JSON.stringify(data)]);
  const save = async () => {
    try { const saved = await request('/api/config/security', { method: 'PUT', body: { allowlist: (draft.allowlistText || '').split(',').map((x) => x.trim()).filter(Boolean), deny_keywords: (draft.denyText || '').split(',').map((x) => x.trim()).filter(Boolean), approval_required: (draft.approvalText || '').split(',').map((x) => x.trim()).filter(Boolean), unattended_policy: draft.unattended_policy || 'deny' } }); setData(saved); toastMessage(setToast, 'success', '安全配置已保存'); }
    catch (err) { toastMessage(setToast, 'error', `保存失败：${err.message}`); }
  };
  const checkCommand = async () => {
    try { const res = await request(`/api/security/check?command=${encodeURIComponent(command)}`); setCheck(res); toastMessage(setToast, res.blocked ? 'warn' : 'success', res.blocked ? '命令被安全策略阻断' : '命令通过安全检查'); }
    catch (err) { toastMessage(setToast, 'error', `检查失败：${err.message}`); }
  };
  return <div className="config-two-col"><Card title="安全策略" action={<button type="button" onClick={reload}><RefreshCw size={14} />刷新</button>}><div className="field"><label>允许命令</label><textarea value={draft.allowlistText || ''} onChange={(e) => setDraft({ ...draft, allowlistText: e.target.value })} /></div><div className="field"><label>拒绝关键字</label><textarea value={draft.denyText || ''} onChange={(e) => setDraft({ ...draft, denyText: e.target.value })} /></div><div className="field"><label>需审批命令</label><textarea value={draft.approvalText || ''} onChange={(e) => setDraft({ ...draft, approvalText: e.target.value })} /></div><div className="field"><label>无人值守策略</label><select value={draft.unattended_policy || 'deny'} onChange={(e) => setDraft({ ...draft, unattended_policy: e.target.value })}><option value="deny">deny</option><option value="approval">approval</option><option value="allow">allow</option></select></div><button type="button" className="primary" onClick={save}><Save size={14} />保存安全策略</button></Card><Card title="命令验证"><div className="field"><label>待检查命令</label><input value={command} onChange={(e) => setCommand(e.target.value)} /></div><button type="button" onClick={checkCommand}><ShieldCheck size={14} />检查命令</button>{check && <JsonBlock data={check} setToast={setToast} />}</Card></div>;
}

function ImportExportConfig({ setToast }) {
  const [payload, setPayload] = useState('');
  const [result, setResult] = useState(null);
  const exportConfig = async () => {
    try { const data = await request('/api/config/export'); const text = JSON.stringify(data, null, 2); setPayload(text); setResult({ exported: true }); toastMessage(setToast, 'success', '配置已导出到编辑框'); }
    catch (err) { toastMessage(setToast, 'error', `导出失败：${err.message}`); }
  };
  const validate = async () => {
    try { const res = await request('/api/config/validate', { method: 'POST', body: JSON.parse(payload || '{}') }); setResult(res); toastMessage(setToast, res.valid ? 'success' : 'warn', res.valid ? '配置验证通过' : '配置验证发现问题'); }
    catch (err) { toastMessage(setToast, 'error', `验证失败：${err.message}`); }
  };
  const importConfig = async () => {
    try { const res = await request('/api/config/import', { method: 'POST', body: JSON.parse(payload || '{}') }); setResult(res); toastMessage(setToast, 'success', '配置已导入'); }
    catch (err) { toastMessage(setToast, 'error', `导入失败：${err.message}`); }
  };
  return <Card title="配置导入导出"><div className="button-row"><button type="button" onClick={exportConfig}><Download size={16} />导出配置</button><button type="button" onClick={validate}><ClipboardCheck size={16} />验证配置</button><button type="button" className="primary" onClick={importConfig}><Upload size={16} />导入配置</button><button type="button" onClick={() => downloadText('netmind-config.json', payload)}><Download size={16} />下载 JSON</button></div><textarea className="big-editor" value={payload} onChange={(e) => setPayload(e.target.value)} placeholder="点击导出配置，或粘贴 JSON 后验证 / 导入" />{result && <JsonBlock data={result} setToast={setToast} />}</Card>;
}

function EditableList({ title, rows, idKey, onEdit, onRefresh, draft, setDraft, onSave, fields, extraAction, setToast }) {
  return (
    <div className="config-two-col">
      <Card title={`${title}列表`} action={<button type="button" onClick={onRefresh}><RefreshCw size={14} />刷新</button>}>
        <div className="list-cards">{rows.map((row) => <button type="button" key={row[idKey]} onClick={() => onEdit(row)}><Edit3 size={17} /><div><b>{row.display_name || row[idKey]}</b><small>{row.description || row.name || row.level || row.id}</small></div><ChevronRight size={15} /></button>)}</div>
      </Card>
      <Card title={`编辑${title}`} action={<button type="button" className="primary" onClick={onSave}><Save size={14} />保存</button>}>
        <FormFields draft={draft} setDraft={setDraft} fields={fields} />
        {'enabled' in draft && <label className="checkline"><input type="checkbox" checked={draft.enabled !== false} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用</label>}
        <div className="button-row">{extraAction}<button type="button" onClick={() => copyText(draft, setToast)}><Copy size={14} />复制草稿</button></div>
      </Card>
    </div>
  );
}

function FormFields({ draft, setDraft, fields }) {
  return <div className="form-grid">{fields.map(([key, label, type = 'text', options]) => <div key={key} className={`field ${type === 'textarea' ? 'span-2' : ''}`}><label>{label}</label>{type === 'textarea' ? <textarea value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} /> : type === 'select' ? <select value={draft[key] || options?.[0]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}>{options.map((o) => <option key={o} value={o}>{o}</option>)}</select> : <input type={type} value={draft[key] ?? ''} onChange={(e) => setDraft({ ...draft, [key]: type === 'number' ? Number(e.target.value) : e.target.value })} />}</div>)}</div>;
}

function SearchBox({ value, onChange, placeholder }) {
  return <div className="search-box"><Search size={16} /><input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} /></div>;
}

function InlineError({ text }) { return <div className="inline-message error"><XCircle size={16} />{text}</div>; }
function InlineWarn({ text }) { return <div className="inline-message warn"><AlertTriangle size={16} />{text}</div>; }
function InlineSuccess({ text }) { return <div className="inline-message success"><CheckCircle2 size={16} />{text}</div>; }

createRoot(document.getElementById('root')).render(<Shell />);
