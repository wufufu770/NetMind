# 架构说明

```text
Frontend React Console / CLI
        ↓ HTTP + WebSocket
FastAPI API Gateway
        ↓
Workflow Orchestrator
        ↓
IntentAgent → PlannerAgent → VerifierAgent → DeployAgent
        ↓                                   ↓
TelemetryAgent → DiagnosisAgent → HealingAgent
        ↓
RuleEngine / SecurityChecker / TransactionManager / DriverRegistry
        ↓
SimulationDriver 默认安全执行；Mininet/SSH/NETCONF 可替换
```

默认运行模式是 `simulation`，所有网络命令进入 SecurityChecker 后只写入审计日志，不会修改本机网络。生产环境可在 `.env` 中设置 `NETMIND_DRIVER=mininet` 并以具备网络权限的容器运行。
