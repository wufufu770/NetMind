# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Added
- 变更提案（config-diff）：下发前把「将改什么」显式摊开，危险项排前并标注必须走审批流，输出可评审的 Markdown（`core/config_diff.py`，8 个测试）
- 无限迭代循环协议：BUILD → TEST → IMPROVE → PLAN → STATE，每轮一个可验证增量，门禁声明失败退路，状态落盘保证永远有下一步（`.netmind-loop/`）
- 去 AI 味密度门：客户可见面按密度检测空洞套话、无源数字、元评论、装饰性 emoji、过度格式化（`scripts/copy_lint.py`）
- CI 新增 `loop-gates` 与 `supply-chain` 两个 job（后者含 pip-audit / npm audit / SBOM）
- `LICENSE`（MIT 文件此前缺失，尽管 README 与 pyproject 均声明 MIT）
- `CLA.md` 草案：记录「已接受贡献不可追溯改协议」这一窗口，并给出 DCO 方向
- `CONTRIBUTING.md` 第 5 条：营销面可核查律（规则 2 从代码平移到客户可见文本）
- Dependabot 覆盖 pip / npm / github-actions 三条

### Changed
- 门禁退路体系：新增 `blocked` 状态与 `loop.py block`，避免循环停在需人工判断的待办上
- 死模块门禁由 `autofix` 降级为 `block`——移动代码需要语义判断，不满足 autofix 门槛

### Removed
- `core/sqlite_store.py`：完整但从未接线的 23 行 KV 存储。零引用属死代码；如商业化确需真实 DB 后端，另立一轮重新实现并接线（git 历史可取回）


### Security
- 危险操作门禁按语义判定：del-flows / mod-flows / iptables -F / link down / route del / addr del，与设备名无关。
- 回滚特权基于服务端签发的 cookie 登记表；未登记命令走审批门禁。
- POST `/api/deploy/{id}/rollback` 真实执行回滚计划并逐命令校验；未部署返回 409。

### Changed
- `DeployResult.rollback_complete` 区分回滚全部成功与部分尝试。
- tc 接口名严格策略仅限仿真；真实驱动接受标准接口名。
- 前端 security_passed / rollback_ready 取自实际结果。

### Removed
- `backend/build` 构建产物出库；`.gitignore` 增加 `build/`。

### Added
- `netmind audit` 只读巡检 v1 与对应回归测试（后端 67 项）。

## [0.1.0] - 2026-08-22

First public release. The closed loop is real where it claims to be, and honestly labelled where it is not.

### Added
- Intent-driven closed loop: NL intent → plan → verify → deploy → telemetry → diagnose → heal, with offline rule-engine fallback and optional OpenAI-compatible LLMs (DeepSeek / Qwen / OpenAI / Ollama presets).
- `netmind diagnose <containerlab-topology>`: structure checks (dangling endpoints, IP conflicts, isolation, invalid mgmt addresses), optional live interface collection via napalm, cached LLM root-cause analysis.
- Policy safety: semantic conflict detection (QoS guarantee × ACL deny), security allowlist/deny-keywords checker with approval workflow and unattended-policy gate, transactional rollback plans that themselves pass the security checker.
- Real device drivers behind explicit gates: netmiko execution + napalm read-only collection (`NETMIND_ENABLE_REAL_COMMANDS`), ncclient for NETCONF; everything dry-run by default.
- Optional bearer-token auth for all non-GET API requests (`NETMIND_ADMIN_TOKEN`).
- LangGraph adapter: uses real LangGraph StateGraph when installed, falls back to a built-in compatible engine.
- React dashboard (9 pages) + WebSocket events; MCP-style tool registry (24 tools) exposed as `netmind-tool-gateway/1.0`.
- Packaging: `pip install ./backend` provides the `netmind` CLI; single-sourced version.

### Changed
- Deployment results carry an explicit `mode` field (`simulated` | `dry-run` | `real`); dry-run never reports success as a real push.
- Telemetry snapshots are labelled with their source (`simulated` by default).

### Removed
- Competition-era vanity modules (feature-matrix completion scores, benchmark runner, repository status probes) and the fake mininet driver stub.

### Fixed
- Deleted configuration (models/agents/templates/workflows) no longer resurrects after restart: seeding only runs on an empty store.
- Store persistence is debounced (dirty-flag + background flusher) instead of a full JSON dump per request.
- Step durations in audit trails are measured, no longer padded with hardcoded offsets.
