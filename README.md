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
| Healing action | ✅ Real — 处置是真命令而非描述串：过安全门 → TransactionManager 下发 → 重测对比（`core/remediation.py`）；`congestion` 路径已在真实设备端到端跑通（150.277ms→0.203ms，设备侧 qdisc `netem`→`noqueue` 读回确认）；⚠️ `link_down` 路径未在设备上实跑；真实生产故障未验证 |
| Offline rule engine + mock model | ✅ Real |
| Real LLM calls | ✅ Real (API key required) |
| Topology & telemetry data | ✅ Real when a probe target is configured (`NETMIND_PROBE_TARGET`) — ICMP from the monitored device; ⚠️ falls back to a **labelled** simulator when no probe target is set (snapshot carries `source=simulated`, diagnosis confidence is discounted accordingly) |
| Policy deployment on devices | ✅ Real — 真 SSH 下发与真回滚已在真实容器上验证（写入→读回确认→回滚→确认失效）；⚠️ 仍默认 dry-run，需显式 `NETMIND_ENABLE_REAL_COMMANDS=true` + 凭据 |
| Read-only device collection / audit | ✅ Real — 能力矩阵见 `diagnose/vendor_matrix.py`（`GET /api/vendors`）；每家厂商带**验证等级**，未知型号**不猜驱动**、如实拒绝 |
| Dependency vulnerabilities | ✅ 0 known (`pip-audit` + `npm audit`, both in CI) |
| Frontend tests | ✅ 12 cases on extracted display helpers (node built-in runner, no test framework) |
| Default security | ✅ Safe by default — no token ⇒ loopback-only (403); token ⇒ all methods incl. GET; `/healthz` public, `/metrics` authenticated |
| Self observability | ✅ Real — `/healthz` + `/metrics` (p50/p95/p99 per endpoint, error counts) |
| Dashboard metrics | ✅ Derived from real state (`core/dashboard.py`); ⚠️ **no SLA attainment figure** — it needs an agreed SLO target, which the project does not define, so the field is `null` with a stated reason rather than a number; risk entries appear only when telemetry supports them, each carrying its `evidence` |
| SLA feasibility check | ✅ Real — `POST /api/telemetry/predict-sla` judges the measured history against **the target the caller supplies**, returning which target was used and which metrics breached; with no target supplied it returns the measured averages and `feasible: null` rather than picking a threshold on the user's behalf |
| AI recovery review | ✅ Real — re-runs the rule engine over recent executions and compares against what was recorded; entries it cannot evaluate are listed in `undecidable` and force an `indeterminate`/`partial` verdict instead of counting as "no conflict" |
| Data durability | ✅ Atomic write (fsync + rename + dir fsync) + `scripts/data_ops.py` backup/restore/drill; drill 在 CI 里每次真跑 |
| Rollback semantics | ✅ Covered — rollback only touches *applied* commands; cookies/routes released after rollback; security-blocked ⇒ no rollback, driver-failed ⇒ conservative rollback |
| Post-verify rollback | ✅ Real — 下发成功但重测无改善时**真调** `TransactionManager.rollback()` 撤销（`anomaly_traffic` 路径已在真实设备验证：下发限速 → 重测无改善 → 设备侧 qdisc 读回确认已撤销）；⚠️ `congestion` 撤不回来（处置删了设备原有整形但未记录参数），此时如实报「无法自动回滚」并给出诊断命令，不拿只读检查冒充回滚 |
| Test reproducibility | ✅ Gate `tests-are-reproducible` runs the suite twice; same pass count required |
| Concurrency | ✅ 20×20=1040 requests, **0 errors**, data intact; latency baseline in `docs/load-test-baseline.md` (known limit: single-process only) |
| Rate limiting | ✅ Per-source token buckets (write 5/s, read 50/s); `NETMIND_RATE_LIMIT=off` for bulk import; known limit: in-process only (multi-worker multiplies the limit) |

## Vendor support

不要在这里看「支持哪些厂商」——那会与实态漂移。看矩阵：

```bash
GET /api/vendors       # JSON
GET /api/vendors.md    # Markdown 表
```

矩阵每条都带验证等级：**verified**（已在真实设备跑通采集）· **declared**（映射与依赖齐备，未在真实设备验过）· **blocked**（缺驱动插件，标出卡在哪）。

生成源是 `backend/app/diagnose/vendor_matrix.py`，有测试保证它与 `drivers.py` 的映射一致。

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
