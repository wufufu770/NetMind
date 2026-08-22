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
SimulationDriver 默认安全执行；SSH(NETCONF) 驱动默认干跑，需 NETMIND_ENABLE_REAL_COMMANDS=true 才触碰真实设备
```

默认运行模式是 `simulation`，所有网络命令进入 SecurityChecker 后只写入审计日志，不会修改本机网络。接入真实设备时在 `.env` 中设置 `NETMIND_DRIVER=ssh`（或 `netconf`）并提供凭据，显式设置 `NETMIND_ENABLE_REAL_COMMANDS=true` 前所有命令保持干跑。
