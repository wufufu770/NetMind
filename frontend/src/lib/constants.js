/** 静态数据：主题预设、字体、状态文案、示例意图、模型预设。
 *
 * 从 App.jsx（1887 行）抽出来的纯数据段，零逻辑零 JSX。
 * 抽出来不是为了「文件变小」——App.jsx 里还堆着十来个页面组件，那是另一回事。
 * 目的是让**可测的东西离开入口文件**：`node --test` 只能直接 import 纯模块，
 * 而 App.jsx 是带 JSX 的入口，`request()` 这种承载认证契约的函数此前一行测试都写不了。
 */

/** 导航与配置页共用文案。改这里等于改用户看到的中文。 */
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

export { themePresets };
export { fontChoices };
export { statusLabels };
export { issueCodeLabels };
export { sampleIntents };
export { fallbackModelPresets };
