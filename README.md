# NetMind — 意图驱动的自治网络平台


面向智能体互联网的意图驱动跨域自治网络平台。用户以自然语言描述网络需求，8 个 AI Agent 协同完成意图解析、策略规划、冲突检测、配置下发与闭环自愈。

## 快速启动

```bash
docker compose up -d --build
```

- 前端：http://localhost:5173
- 后端 API：http://localhost:8000/docs

## 功能特性

- **自然语言驱动**：输入业务意图，自动编译为 DSL 并规划网络策略
- **8 Agent 协同**：IntentAgent → PlannerAgent → VerifierAgent → DeployAgent → TelemetryAgent → DiagnosisAgent → HealingAgent 完整闭环
- **LangGraph 适配**：自动检测 langgraph，已安装使用真实引擎，未安装降级兼容引擎
- **MCP 工具协议**：标准化工具注册与调用，24 个内置工具
- **多工作流支持**：默认闭环、安全审批、遥测诊断、跨域协商
- **模板管理**：意图模板 CRUD，模板建议与匹配
- **Agent 管理**：Agent 增删改、模型绑定、cron 调度
- **安全仿真双模式**：默认仿真不修改真实网络，可切换真实设备 + SecurityChecker + 审批流

## 页面

| 页面 | 功能 |
|------|------|
| 运行态势 | 网络指标、拓扑、告警、事件流 |
| 网络遥测 | 实时遥测、故障注入、异常检测、自愈 |
| 审计日志 | 日志筛选、搜索、导出 |
| 意图编排 | 自然语言意图输入、DSL 编译、工作流选择、模板管理 |
| Agent 管理 | Agent 增删改、调度控制、工作流保存 |
| 策略中心 | 策略验证、自动修复、审批执行、回滚计划 |
| 合规报告 | Markdown/HTML/PDF 报告生成 |
| 系统配置 | 主题字体、模型、规则、工具、工作流、安全、导入导出 |
| 系统自检 | F1-F15 一键验收 |

## 技术栈

Python FastAPI + React + WebSocket + LangGraph 适配 + MCP 协议 + Docker

## 文档

| 文档 | 说明 |
|------|------|
| [API 参考](docs/API.md) | 接口速查 |
| [架构说明](docs/ARCHITECTURE.md) | 系统架构与数据流 |
| [功能矩阵](docs/FEATURE_MATRIX.md) | 66 项功能清单 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|------|
| `NETMIND_DRIVER` | 驱动模式 | `simulation` |
| `NETMIND_ADMIN_TOKEN` | 鉴权令牌 | `netmind-local-admin` |
| `NETMIND_CORS_ORIGINS` | 跨域允许源 | `http://localhost:5173` |

## 测试

```bash
cd backend && pytest -q
python scripts/validate_project.py
```

## License

MIT
