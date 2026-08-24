from __future__ import annotations
from typing import Dict, List, Any
from pathlib import Path
import atexit, json, os, re, threading, time
from .schemas import *

MAX_LOGS=2000
MAX_EXECUTIONS=500
MAX_TELEMETRY=2000
AUTOSAVE_INTERVAL=2.0

DATA_PATH = Path(os.getenv('NETMIND_DATA_FILE', Path(__file__).resolve().parents[2] / 'data' / 'netmind_store.json'))

class PersistentStore:
    """Small durable store used by the packaged build.

    Default persistence is a JSON file so the project can run everywhere. The API
    boundary is intentionally narrow so it can be replaced by PostgreSQL/SQLAlchemy
    without changing routers or business logic.
    """
    def __init__(self):
        self.executions: Dict[str, Execution] = {}
        self.logs: List[LogEntry] = []
        self.approvals: Dict[str, Approval] = {}
        self.telemetry: List[TelemetrySnapshot] = []
        self.rules: Dict[str, Rule] = {}
        self.models: Dict[str, ModelConfig] = {}
        self.agents: Dict[str, AgentConfig] = {}
        self.tools: Dict[str, ToolConfig] = {}
        self.workflows: Dict[str, WorkflowConfig] = {}
        self.theme = ThemeConfig()
        self.mcp_servers: Dict[str, Dict[str, Any]] = {}
        self.credentials: Dict[str, CredentialConfig] = {}
        self.templates: Dict[str, str] = {}
        self.agent_schedules: Dict[str, Dict[str, Any]] = {}
        # 已签发流表 cookie -> 签发 execution_id；回滚仅放行已登记项。
        self.flow_cookies: Dict[str, str] = {}
        self._lock=threading.RLock()
        self._dirty=False
        self._last_save=0.0
        if DATA_PATH.exists():
            self.load()
        else:
            self.seed()

    def _dump_dict(self, rows: Dict[str, BaseModel]) -> Dict[str, Any]:
        return {k: v.model_dump(mode='json') for k, v in rows.items()}

    def to_json(self) -> Dict[str, Any]:
        return {
            'executions': {k: v.model_dump(mode='json') for k, v in list(self.executions.items())[-200:]},
            'logs': [x.model_dump(mode='json') for x in self.logs[-MAX_LOGS:]],
            'approvals': self._dump_dict(self.approvals),
            'telemetry': [x.model_dump(mode='json') for x in self.telemetry[-MAX_TELEMETRY:]],
            'rules': self._dump_dict(self.rules),
            'models': self._dump_dict(self.models),
            'agents': self._dump_dict(self.agents),
            'tools': self._dump_dict(self.tools),
            'workflows': self._dump_dict(self.workflows),
            'theme': self.theme.model_dump(mode='json'),
            'mcp_servers': self.mcp_servers,
            'credentials': {k: {**v.model_dump(mode='json'), 'secret_ref': '***' if v.secret_ref else ''} for k, v in self.credentials.items()},
            'templates': self.templates,
            'agent_schedules': self.agent_schedules,
            'flow_cookies': dict(self.flow_cookies),
        }

    def save(self) -> None:
        with self._lock:
            payload=self.to_json()
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(DATA_PATH)
        self._last_save=time.time()
        self._dirty=False

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty=True
        if time.time()-self._last_save >= AUTOSAVE_INTERVAL:
            try:
                self.save()
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            pending=self._dirty
        if pending:
            self.save()

    def start_autosave(self) -> None:
        def _loop():
            while True:
                time.sleep(AUTOSAVE_INTERVAL)
                try:
                    self.flush()
                except Exception:
                    pass
        threading.Thread(target=_loop, daemon=True, name='netmind-autosave').start()

    def load(self) -> None:
        if not DATA_PATH.exists():
            return
        try:
            raw = json.loads(DATA_PATH.read_text(encoding='utf-8'))
            self.executions.update({k: Execution(**v) for k, v in raw.get('executions', {}).items()})
            self.logs = [LogEntry(**v) for v in raw.get('logs', [])]
            self.approvals.update({k: Approval(**v) for k, v in raw.get('approvals', {}).items()})
            self.telemetry = [TelemetrySnapshot(**v) for v in raw.get('telemetry', [])]
            self.rules.update({k: Rule(**v) for k, v in raw.get('rules', {}).items()})
            self.models.update({k: ModelConfig(**v) for k, v in raw.get('models', {}).items()})
            self.agents.update({k: AgentConfig(**v) for k, v in raw.get('agents', {}).items()})
            self.tools.update({k: ToolConfig(**v) for k, v in raw.get('tools', {}).items()})
            self.workflows.update({k: WorkflowConfig(**v) for k, v in raw.get('workflows', {}).items()})
            if raw.get('theme'):
                self.theme = ThemeConfig(**raw['theme'])
            self.mcp_servers.update(raw.get('mcp_servers', {}))
            self.credentials.update({k: CredentialConfig(**{**v, 'secret_ref': '' if v.get('secret_ref') == '***' else v.get('secret_ref','')}) for k, v in raw.get('credentials', {}).items()})
            self.templates.update(raw.get('templates', {}))
            self.agent_schedules.update(raw.get('agent_schedules', {}))
            self.flow_cookies.update({str(k): str(v) for k, v in raw.get('flow_cookies', {}).items()})
            if len(self.executions) > 200:
                self.executions = dict(list(self.executions.items())[-200:])
        except Exception as exc:
            # Preserve bootability; surface the error in logs.
            self.logs.append(LogEntry(source='store', level='error', message=f'failed to load persisted store: {exc}'))

    def reset_runtime(self) -> None:
        self.executions.clear(); self.logs.clear(); self.approvals.clear(); self.telemetry.clear()
        self.save()

    COOKIE_RE = re.compile(r'cookie=(0x4e65744d[0-9a-fA-F]{8})')

    def register_flow_cookies(self, commands: list[str], execution_id: str) -> int:
        """把系统规划命令中出现的 NetMind 格式 cookie 登记为已签发。返回新登记数量。"""
        added = 0
        with self._lock:
            for cmd in commands or []:
                for m in self.COOKIE_RE.finditer(cmd or ''):
                    cookie = m.group(1)
                    if cookie not in self.flow_cookies:
                        self.flow_cookies[cookie] = execution_id
                        added += 1
            self.mark_dirty()
        return added

    def has_flow_cookie(self, command: str) -> bool:
        """命令中携带的任一 NetMind cookie 是否为系统登记签发的。"""
        return any(m.group(1) in self.flow_cookies for m in self.COOKIE_RE.finditer(command or ''))

    def log(self, source: str, message: str, level: str='info', execution_id: str|None=None, data: dict|None=None):
        entry=LogEntry(source=source, message=message, level=level, execution_id=execution_id, data=data or {})
        self.logs.append(entry)
        if len(self.logs) > MAX_LOGS:
            self.logs = self.logs[-MAX_LOGS:]
        return entry

    def put_execution(self, execution: Execution) -> None:
        self.executions[execution.execution_id]=execution
        while len(self.executions) > MAX_EXECUTIONS:
            oldest=next(iter(self.executions))
            self.executions.pop(oldest, None)

    def record_telemetry(self, snap: TelemetrySnapshot) -> None:
        self.telemetry.append(snap)
        if len(self.telemetry) > MAX_TELEMETRY:
            self.telemetry[:] = self.telemetry[-MAX_TELEMETRY:]

    def seed(self):
        self.templates = {
            'defense': '今晚8点保障答辩视频会议，教师终端到会议服务器延迟低于50ms，访客网络限速5Mbps',
            'guest': '访客网络限速5Mbps，并禁止访问实验室服务器',
            'lab': '实验室网络隔离，只允许教师终端访问实验服务器',
            'backup': '凌晨2点到4点保障数据库备份链路，带宽不低于50Mbps',
            'exam': '考试期间禁止学生终端访问外网，只允许访问考试服务器',
            'voip': '保障内部 VoIP 通话低延迟，抖动低于10ms'
        }
        self.models['mock']=ModelConfig(id='mock', name='Mock LLM', base_url='local://mock', model_id='mock-model', online=True)
        self.models['deepseek']=ModelConfig(id='deepseek', name='DeepSeek Compatible', base_url='https://api.deepseek.com/v1', model_id='deepseek-chat', online=False)
        self.models['qwen']=ModelConfig(id='qwen', name='Qwen Compatible', base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', model_id='qwen-plus', online=False)
        self.models['ollama']=ModelConfig(id='ollama', name='Ollama Local', base_url='http://localhost:11434/v1', model_id='llama3.1', online=False)
        prompt_map={
            'OrchestratorAgent':'你是 NetMind 主调度 Agent。只负责拆解任务、选择工作流、汇总状态和决定是否需要审批；禁止直接执行网络命令。输出必须结构化、可审计。',
            'IntentAgent':'你是意图解析 Agent。必须把用户自然语言转成 IntentDSL JSON；不确定时设置 ambiguous=true 并给 candidates；禁止编造不存在的拓扑节点。',
            'PlannerAgent':'你是策略规划 Agent。必须先参考工具上下文(topology/telemetry/SLA/规则命中)，再输出 PolicySet JSON；每条策略必须包含 commands 和 rollback_commands。模型失败时允许规则降级。',
            'VerifierAgent':'你是策略验证 Agent。检查 ACL/QoS/Route 冲突、路径可达性、SLA 可行性和安全命令；高风险必须 need_human=true。',
            'DeployAgent':'你是配置下发 Agent。必须先 security_check，再事务执行；任何失败必须回滚；禁止执行未白名单命令。',
            'TelemetryAgent':'你是遥测采集 Agent。只采集和推送指标，不修改网络；连续异常才触发诊断。',
            'DiagnosisAgent':'你是诊断 Agent。根据遥测窗口和拓扑证据判断 congestion/link_down/anomaly_traffic/config_error/normal；不执行修复。',
            'HealingAgent':'你是自愈 Agent。只执行一个经过审批或策略允许的原子动作，并记录前后指标对比。',
            'ConversationAgent':'你是只读解释 Agent。只能回答状态、策略原因、配置含义和报告摘要，不做任何下发动作。'
        }
        for name, level, tools in [
            ('OrchestratorAgent','primary',['assign_task','workflow_state','free_workflow_selector']),
            ('IntentAgent','secondary',['model_adapter','rule_engine_match','schema_validate','free_template_recommender']),
            ('PlannerAgent','secondary',['rule_engine_match','topology_tool','telemetry_tool','free_path_finder','free_sla_estimator','free_acl_conflict_scan','model_adapter']),
            ('VerifierAgent','secondary',['policy_verifier','topology_tool','security_check','free_policy_diff','free_acl_conflict_scan']),
            ('DeployAgent','secondary',['security_check','network_tool','transaction_manager','free_rollback_preview']),
            ('TelemetryAgent','tertiary',['telemetry_tool','free_latency_probe','free_bandwidth_estimator','websocket_publish']),
            ('DiagnosisAgent','tertiary',['diagnosis_rules','topology_tool','free_anomaly_classifier']),
            ('HealingAgent','tertiary',['network_tool','transaction_manager','rollback_manager','free_healing_advisor']),
            ('ConversationAgent','secondary',['read_only_query','report_generator','free_state_explainer'])
        ]:
            self.agents[name]=AgentConfig(name=name, level=level, allowed_tools=tools, model_id='mock', prompt=prompt_map[name])
        for tool, desc in {
            'ovs_tool':'Open vSwitch flow operation wrapper, safe by default',
            'tc_tool':'Linux tc QoS/limit wrapper, safe by default',
            'acl_tool':'iptables/nftables ACL wrapper, safe by default',
            'telemetry_tool':'采集或模拟延迟、丢包、吞吐量',
            'topology_tool':'读取拓扑快照与节点详情',
            'security_check':'命令白名单、黑名单与参数约束检查',
            'rule_engine_match':'规则引擎命中与策略模板匹配',
            'report_generator':'Markdown/HTML/PDF 报告生成',
            'workflow_editor':'工作流配置保存、选择和运行',
            'mcp_loader':'外部 MCP server dry-run 接入',
            'ssh_driver':'SSH 物理设备驱动入口',
            'netconf_driver':'NETCONF 设备驱动入口',
            'free_latency_probe':'内置延迟探测工具，适用于本地仿真与演示验证',
            'free_bandwidth_estimator':'内置带宽估算工具，适用于策略规划上下文',
            'free_path_finder':'内置路径计算工具，基于拓扑快照执行可达性分析',
            'free_sla_estimator':'内置 SLA 可行性评估工具',
            'free_acl_conflict_scan':'内置 ACL 冲突扫描工具',
            'free_policy_diff':'内置策略差异比较工具',
            'free_cron_explain':'内置调度表达式解释工具',
            'free_template_recommender':'内置意图模板推荐工具',
            'free_rollback_preview':'内置回滚计划预览工具',
            'free_anomaly_classifier':'内置异常分类工具',
            'free_healing_advisor':'内置处置建议工具',
            'free_state_explainer':'内置系统状态解释工具'
        }.items():
            self.tools[tool]=ToolConfig(name=tool, description=desc)
        self.workflows['default']=WorkflowConfig(id='default', name='默认闭环工作流', graph={'nodes':['OrchestratorAgent','IntentAgent','PlannerAgent','VerifierAgent','DeployAgent','TelemetryAgent','DiagnosisAgent','HealingAgent'], 'edges':[('OrchestratorAgent','IntentAgent'),('IntentAgent','PlannerAgent'),('PlannerAgent','VerifierAgent'),('VerifierAgent','DeployAgent'),('DeployAgent','TelemetryAgent'),('TelemetryAgent','DiagnosisAgent'),('DiagnosisAgent','HealingAgent')]})
        self.workflows['safe_approval']=WorkflowConfig(id='safe_approval', name='安全审批工作流', graph={'nodes':['OrchestratorAgent','IntentAgent','PlannerAgent','VerifierAgent','HumanApproval','DeployAgent','TelemetryAgent'], 'edges':[('OrchestratorAgent','IntentAgent'),('IntentAgent','PlannerAgent'),('PlannerAgent','VerifierAgent'),('VerifierAgent','HumanApproval'),('HumanApproval','DeployAgent'),('DeployAgent','TelemetryAgent')]})
        self.workflows['telemetry_only']=WorkflowConfig(id='telemetry_only', name='只读遥测诊断工作流', graph={'nodes':['OrchestratorAgent','TelemetryAgent','DiagnosisAgent','ConversationAgent'], 'edges':[('OrchestratorAgent','TelemetryAgent'),('TelemetryAgent','DiagnosisAgent'),('DiagnosisAgent','ConversationAgent')]})
        self.workflows['cross_domain']=WorkflowConfig(id='cross_domain', name='跨域协商工作流', graph={'nodes':['OrchestratorAgent','CampusDomainAgent','GuestDomainAgent','CloudDomainAgent','VerifierAgent','DeployAgent'], 'edges':[('OrchestratorAgent','CampusDomainAgent'),('CampusDomainAgent','GuestDomainAgent'),('GuestDomainAgent','CloudDomainAgent'),('CloudDomainAgent','VerifierAgent'),('VerifierAgent','DeployAgent')]})
        business=[
            ('video_meeting_priority','视频会议保障（高优先级）','video_meeting'),('video_meeting_standard','视频会议保障（标准优先级）','video_meeting'),('lab_isolation','实验室网络完全隔离','lab_isolation'),('guest_limit','访客网络限速（通用）','guest_limiting'),('guest_forbid_lab','访客禁止访问实验室','guest_limiting'),('office_priority','办公网带宽优先','office_priority'),('iot_vlan','物联网设备 VLAN 隔离','iot_isolation'),('backup_window','数据库备份窗口保障','backup'),('exam_lockdown','考试环境网络封锁','exam'),('live_stream','直播推流带宽保障','live_stream'),('rdp_low_latency','远程桌面低延迟通道','remote_desktop'),('campus_sync','跨校区数据同步大带宽保障','sync'),('printer_isolation','打印机与内网隔离','printer'),('guest_wifi_isolation','来宾 Wi-Fi 与内网完全隔离','guest_limiting'),('lunch_release','午休时间带宽弹性释放','elastic'),('attack_port_block','受攻击端口自动封锁','security'),('core_cpu_protect','核心交换机 CPU 保护策略','security'),('dns_priority','DNS 服务器优先保障','dns'),('dhcp_ha','DHCP 服务器高可用保障','dhcp'),('camera_upload','监控摄像头流上传保障','camera'),('finance_isolation','财务系统网络隔离','finance'),('rd_limited','研发网段外网访问限制','rd'),('access_control','门禁系统网络高可靠保障','access'),('video_storage','视频录像存储带宽保障','storage'),('api_rate_limit','外部 API 调用限流','api'),('guest_portal','访客门户强制重定向','guest_portal'),('voip_low_latency','内部 VoIP 通话低延迟保障','voip'),('update_limit','软件更新服务器带宽限制','update'),('temp_meeting_wifi','临时会议无线网络优先','meeting_wifi'),('dorm_night','学生宿舍夜间带宽管理','dorm'),('teacher_roaming','教师办公楼无线漫游优化','roaming'),('remote_teaching_upload','远程教学录播上传保障','teaching'),('email_no_loss','电子邮件服务防丢包保障','email'),('snmp_whitelist','网管系统 SNMP 流量白名单','snmp'),('default_best_effort','默认兜底策略','default')]
        for i,(name,desc,biz) in enumerate(business, start=1):
            self.rules[name]=Rule(name=name, description=desc, priority=100-i, match_business=biz, action_template={'source':'rule','rule_id':name})

STORE = PersistentStore()
atexit.register(STORE.flush)
