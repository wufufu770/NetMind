from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class Status(str, Enum):
    waiting='waiting'; running='running'; success='success'; warning='warning'; failed='failed'; approval='approval'

class Target(BaseModel):
    src: str = 'teacher_terminal'
    dst: str = 'meeting_server'
    traffic_type: str = 'video'

class SLA(BaseModel):
    latency_ms: Optional[float] = 50
    packet_loss: Optional[float] = 0.01
    bandwidth_mbps: Optional[float] = 20
    jitter_ms: Optional[float] = None

class Constraints(BaseModel):
    guest_limit_mbps: Optional[float] = 5
    forbid_guest_to_lab: Optional[bool] = True
    allowed_ports: List[int] = Field(default_factory=list)
    denied_ports: List[int] = Field(default_factory=list)
    allowed_protocols: List[str] = Field(default_factory=lambda: ['tcp','udp','icmp'])
    time_range: Optional[Dict[str,str]] = None

class IntentDSL(BaseModel):
    intent_id: str = Field(default_factory=lambda: f'intent-{uuid4().hex[:8]}')
    business: str = 'video_meeting'
    description: str = ''
    tags: List[str] = Field(default_factory=list)
    target: Target = Field(default_factory=Target)
    sla: SLA = Field(default_factory=SLA)
    constraints: Constraints = Field(default_factory=Constraints)
    priority: Literal['low','medium','high','critical'] = 'high'
    recover_policy: Literal['auto_reroute','limit','rollback'] = 'auto_reroute'
    schedule: Optional[Dict[str,str]] = None
    rollback_on_failure: bool = True
    notify_on_completion: bool = False
    ambiguous: bool = False
    candidates: List[str] = Field(default_factory=list)

class IntentRequest(BaseModel):
    text: str
    template_id: Optional[str] = None
    workflow_id: str = 'default'
    dry_run: bool = False

class Policy(BaseModel):
    id: str = Field(default_factory=lambda: f'pol-{uuid4().hex[:6]}')
    type: Literal['qos','acl','route','security','telemetry']
    name: str
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    source: Literal['rule','llm','manual','system'] = 'rule'
    commands: List[str] = Field(default_factory=list)
    rollback_commands: List[str] = Field(default_factory=list)

class PolicySet(BaseModel):
    intent_id: str
    policies: List[Policy] = Field(default_factory=list)
    source: str = 'rule'

class VerificationIssue(BaseModel):
    severity: Literal['info','warning','error']
    code: str
    message: str
    auto_fixable: bool = False
    related_policy_ids: List[str] = Field(default_factory=list)

class VerificationReport(BaseModel):
    passed: bool
    conflicts: List[VerificationIssue] = Field(default_factory=list)
    reachable: bool = True
    sla_feasible: bool = True
    sla_confidence: float = 0.92
    security_passed: bool = True
    rollback_ready: bool = True
    need_human: bool = False
    fixed_policy_set: Optional[PolicySet] = None

class CommandResult(BaseModel):
    command: str
    success: bool
    output: str = ''
    blocked: bool = False
    requires_approval: bool = False

class DeployResult(BaseModel):
    execution_id: str
    executed: List[CommandResult] = Field(default_factory=list)
    rolled_back: bool = False
    success: bool = True

class TelemetrySnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float = 23
    packet_loss: float = 0.0002
    throughput_mbps: float = 82
    src: str = 'teacher_terminal'
    dst: str = 'meeting_server'
    alert: bool = False

class Diagnosis(BaseModel):
    type: Literal['congestion','link_down','anomaly_traffic','config_error','normal'] = 'normal'
    evidence: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.9

class HealingReport(BaseModel):
    healing_id: str = Field(default_factory=lambda: f'heal-{uuid4().hex[:8]}')
    action_taken: str
    before_snapshot: TelemetrySnapshot
    after_snapshot: TelemetrySnapshot
    success: bool = True
    summary: str

class AgentStep(BaseModel):
    agent: str
    status: Status
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    duration_ms: int = 0

class Execution(BaseModel):
    execution_id: str = Field(default_factory=lambda: f'exec-{uuid4().hex[:8]}')
    created_at: datetime = Field(default_factory=datetime.utcnow)
    intent_text: str = ''
    intent: Optional[IntentDSL] = None
    policy_set: Optional[PolicySet] = None
    verification: Optional[VerificationReport] = None
    deploy: Optional[DeployResult] = None
    telemetry: List[TelemetrySnapshot] = Field(default_factory=list)
    diagnosis: Optional[Diagnosis] = None
    healing: Optional[HealingReport] = None
    steps: List[AgentStep] = Field(default_factory=list)
    status: Status = Status.waiting

class LogEntry(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    source: str
    level: Literal['info','warn','error']='info'
    message: str
    execution_id: Optional[str]=None
    data: Dict[str, Any] = Field(default_factory=dict)

class Approval(BaseModel):
    approval_id: str = Field(default_factory=lambda: f'appr-{uuid4().hex[:8]}')
    title: str
    description: str
    status: Literal['pending','approved','rejected','expired']='pending'
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Rule(BaseModel):
    name: str
    description: str
    priority: int = 10
    enabled: bool = True
    match_business: Optional[str] = None
    action_template: Dict[str, Any] = Field(default_factory=dict)

class ModelConfig(BaseModel):
    id: str
    name: str
    base_url: str = ''
    model_id: str = 'mock-model'
    temperature: float = 0.2
    max_tokens: int = 4096
    enabled: bool = True
    online: bool = True

class AgentConfig(BaseModel):
    name: str
    level: Literal['primary','secondary','tertiary']
    model_id: str = 'mock'
    allowed_tools: List[str] = Field(default_factory=list)
    prompt: str = ''

class ToolConfig(BaseModel):
    name: str
    description: str
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

class WorkflowConfig(BaseModel):
    id: str = 'default'
    name: str = '默认闭环工作流'
    graph: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

class ThemeConfig(BaseModel):
    primary: str = '#2970FF'
    background: str = '#0D1117'
    card: str = '#161B22'
    radius: int = 8
    font: str = 'Inter, PingFang SC'

class SystemStatus(BaseModel):
    healthy: bool = True
    driver: str = 'simulation'
    model_online: bool = True
    websocket_clients: int = 0
    active_intents: int = 0
    alerts: int = 0


class CredentialConfig(BaseModel):
    id: str = Field(default_factory=lambda: f'cred-{uuid4().hex[:8]}')
    name: str
    driver: Literal['ssh','netconf','mininet'] = 'ssh'
    host: str = ''
    port: int = 22
    username: str = ''
    secret_ref: str = ''
    enabled: bool = False

class ReportOptions(BaseModel):
    execution_id: str
    include_dsl: bool = True
    include_policy: bool = True
    include_verification: bool = True
    include_deploy: bool = True
    include_telemetry: bool = True
    include_healing: bool = True
    include_logs: bool = True
    include_raw_json: bool = False

class BenchmarkResult(BaseModel):
    total: int
    parsed: int
    planned: int
    verified: int
    deployed: int
    healed: int
    success_rate: float
    average_steps: float

class WorkflowRunRequest(BaseModel):
    workflow_id: str = 'default'
    intent_text: str
    dry_run: bool = False

class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True

class ChatRequest(BaseModel):
    question: str
    model_id: str = 'mock'

class AuditSummary(BaseModel):
    executions: int
    logs: int
    security_events: int
    approvals_pending: int
    healing_events: int
