# NetMind

**Intent-driven network operations agent — from natural language intent to verified, rollback-safe policy changes.**
**意图驱动的网络自治运维 Agent：从自然语言意图到可验证、可回滚的策略变更。**

> **Status: alpha · simulation-first.** Real-device drivers are read-only by default and gated behind an explicit flag. / 状态：alpha · 仿真优先；真实设备驱动默认只读、需显式开启。

## Why

Intent-Based Networking fixes the *interface*; agentic AI closes the *loop*: parse intent → propose change → prove safety → apply under approval → observe → heal.
基于意图的网络解决「接口」问题，Agent AI 闭环「执行」问题：解析意图 → 提出变更 → 证明安全 → 审批下发 → 观测自愈。

## Features

- Closed loop: `IntentAgent → PlannerAgent → VerifierAgent → DeployAgent → TelemetryAgent → DiagnosisAgent → HealingAgent`
- LLM optional; offline rule engine fallback (DeepSeek / Qwen / OpenAI / Ollama presets)
- Policy conflict detection, auto-fix, approval flow, transactional rollback
- Read-only router compliance audit (`netmind audit`)
- containerlab topology diagnose (`netmind diagnose`), optional napalm collection and cached LLM analysis
- React dashboard + WebSocket events; MCP-style tool registry

## What's real / What's simulated

| Capability | State |
|---|---|
| Workflow orchestration, conflict detection, approvals, reports | ✅ Real |
| Config-change proposal (diff, danger marking, reviewable Markdown) | ✅ Real (`core/config_diff.py`, 8 tests) |
| Lab data collection (real ICMP + NIC counters) | ✅ Real (`diagnose/lab_collector.py` + `scripts/lab.sh`, 11 tests on real captures) |
| Routing state | ✅ Real — FRR/zebra 路由表（仅直连+静态，无 OSPF/BGP） |
| Diagnosis thresholds | ⚠️ Calibrated on one lab topology; `throughput` judgement needs a baseline and is skipped when absent |
| Post-apply verification | ✅ Real — `diagnose/closed_loop.py`; `success` 由实测前后对比推出，未重测即 `verified=False`（跑测见 `docs/closed-loop-run-report.md`） |
| Healing action | ⚠️ Verified only in the lab (clearing an injected fault); real-world faults unverified |
| Offline rule engine + mock model | ✅ Real |
| Real LLM calls | ✅ Real (API key required) |
| Topology & telemetry data | ⚠️ Simulated generator |
| Policy deployment on devices | ⚠️ Dry-run by default; real SSH/NETCONF behind `NETMIND_ENABLE_REAL_COMMANDS=true` |
| Read-only device collection / audit | ✅ Real — napalm（eos/junos/ios/nxos 系）+ netmiko 直连（Linux/FRR 系）；未知型号**不猜驱动**，如实拒绝 (`diagnose/drivers.py` / `linux_collect.py`，21 tests) |
| Dependency vulnerabilities | ✅ 0 known (`pip-audit` + `npm audit`, both in CI) |
| Frontend tests | ✅ 12 cases on extracted display helpers (node built-in runner, no test framework) |

## Quick start

```bash
docker compose up -d --build
```

- Dashboard: http://localhost:5173 · API docs: http://localhost:8000/docs

### Local development

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev
pip install -r backend/requirements-drivers.txt   # optional real-device drivers
pip install ./backend                             # provides the `netmind` CLI
```

## Audit & Diagnose

```bash
netmind audit                 # 只读巡检：固件 / SSH 口令面 / UPnP / 防火墙 / 管理端口 / 无线加密（默认模拟，报告显式标注）
netmind audit --mode real     # 连接真实设备（需 NETMIND_ENABLE_REAL_COMMANDS=true 与凭据）

netmind diagnose examples/clab-broken.yml               # 拓扑结构检查 → markdown 报告
netmind diagnose topo.yml --live --host r1=172.20.20.2  # + napalm 接口采集
netmind diagnose topo.yml --llm                         # + LLM 根因分析（结果缓存）
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NETMIND_DRIVER` | `simulation` | `simulation` \| `ssh` \| `netconf` |
| `NETMIND_ENABLE_REAL_COMMANDS` | `false` | Write-execution gate for real devices |
| `NETMIND_ADMIN_TOKEN` | – | Bearer token for all non-GET requests |
| `NETMIND_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `NETMIND_SSH_HOST/_PORT/_USERNAME/_PASSWORD/_DEVICE_TYPE` | – | netmiko connection |
| `NETMIND_NAPALM_DRIVER` | SSH device type | napalm driver for collection |
| `NETMIND_NETCONF_HOST/_PORT/_USERNAME/_PASSWORD` | – | ncclient endpoint |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | – | Optional LLM backends |

## Architecture

![architecture](docs/architecture.svg)

- `backend/app/routers/` — API modules
- `backend/app/core/` — orchestration, verification, telemetry, tools
- `backend/app/drivers/` — device abstraction (`execute()` gated, `collect()` read-only)

## Testing

```bash
cd backend && pytest -q
python scripts/validate_project.py
```

CI runs the suite on Python 3.10–3.12 plus a frontend build.

## Roadmap

1. ~~Phase 1 — Diagnose MVP~~ ✅
2. Phase 2 — Guardrailed healing: config-diff proposals, pre/post-apply verification, rollback
3. Phase 3 — MCP server over JSON-RPC stdio

## License

MIT

- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md)
