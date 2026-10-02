# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Fixed
- **CI 的 SBOM 步骤一直是红的，而且即使跑通也是错的**（外部复核发现，此前我一直只说「supply-chain 已修」）：
  ① `cyclonedx-py environment --outfile x.json -o frontend -t python` 在 cyclonedx-bom 7.5.0 下退出码 2——`-o` 是 `--output-file`（要文件路径，给目录报 can't open 'frontend': Is a directory），`-t` 根本不是合法参数
  ② 更严重：supply-chain job **从不安装 backend/requirements.txt**，用 `environment` 子命令扫的是 runner 环境（pip/pip-audit/cyclonedx-bom），**不是项目依赖**。绿的 SBOM 比红的更危险——采购会拿它当数
  改为 `cyclonedx-py requirements --output-file netmind-sbom.json`（working-directory: backend），从声明文件生成，无需安装，实测 12 个组件覆盖全部声明依赖
- `loop.py` 的 `status` / `gates` 是只读命令却每次都写 state.json——查一眼状态就把已提交的快照弄脏，而脏的正是下次接手时读到的第一份文件
- `cmd_metrics` 把 `gates_total` 写到顶层而打印的是 `metrics.gates_total`，后者永远停在旧值（长期显示 15 而实际 16）
- 指标 `tests_passed` 名实不符：数的是 `def test_` 定义个数，parametrize 展开的用例没算进去（119 vs 实际 124），且「定义数」既不是用例数也不是通过数。改用 pytest --collect-only 的权威结果并更名为 `tests_collected`

### Added
- 新门禁 `sbom-covers-declared-deps`：**把 CI YAML 里写的 SBOM 命令真跑一遍**，校验产物是合法 CycloneDX 且覆盖 requirements.txt 里每个声明依赖。已反验：换回旧写法会被拦下

- 厂商能力矩阵（`diagnose/vendor_matrix.py` + `GET /api/vendors`、`/api/vendors.md`）。每家厂商带**验证等级**：verified（已在真实设备跑通采集）/ declared（映射与依赖齐备未验）/ blocked（缺插件，标出卡在哪）。README 不再自述厂商清单，只引用矩阵
- 映射表补 Cisco 系 kind（`ios`/`iosxe`/`iosv`/`cat9k`→`ios`，`nxos`/`nxos_ssh`→`nxos`，`iosxr`→`iosxr`）——此前厂商矩阵声称支持而代码里根本没有这些 kind

### Fixed
- 厂商支持一度只是 README 的一句描述加 drivers.py 的映射表，两处都可能与实态漂移（此前已漂移过一次：映射列了 nokia/srl 而依赖未声明插件）。现改为代码可导出的矩阵，并有门禁与测试锁住「矩阵与映射不得不一致」

- Linux/FRR 系设备的只读采集走 netmiko 直连（`diagnose/linux_collect.py`）。napalm 5.2 核心驱不了这类设备，而实验台拓扑正是这类型——原实现只挂了 napalm 一条路，导致诚实表的「read-only collection ✅ Real」对 Linux/FRR 从来不成立。现实测可采到真实接口状态/路由表/uptime
- 显式驱动映射（`diagnose/drivers.py`）：未知 kind 不再静默兜底成 Arista EOS
- `requirements-drivers.txt` 补可选插件 `napalm-nokia` / `napalm-srl`（此前映射表列了这两个驱动但依赖里从未声明，永远走不通）
- 真实采集结果 fixture `tests/fixtures/lab/live-collection.json`（真 SSH 端点，含正例与两个反例）

### Fixed
- **驱动映射三处错误**：① 映射到 napalm 不存在的 `'linux'`（所有 Linux/FRR 设备必然 ModuleImportError，而错误被混进 errors 看起来像「设备连不上」）② 兜底 `'else eos'` 把任何未知型号当 Arista 下命令 ③ `nokia`/`srl` 两个驱动在声明依赖下永远不可用
- 采集回来的用法/报错文本不再当作数据存储：BusyBox 的 `ip` 不认 `-br`，会把用法说明打回来，此前被原样收进结果——「看起来有数据其实是报错」的污染最难发现
- `send_command(strip=True)` 是 napalm 签名，netmiko 的 `BaseConnection` 不收（实测 TypeError）

- 真实 FRR/zebra 路由表 fixture（`frr-routing-table.txt` / `frr-routing-table-r1.txt`），补上此前缺失的路由数据维度
- 新门禁 `routing-data-is-real`：校验路由 fixture 含真实路由行、且记录了 zebra 对 `SYS_ADMIN` 的依赖
- `scripts/lab.sh measure` 增加 FRR 守护进程状态与真实路由表输出

### Fixed
- `scripts/lab.sh` 三个自埋的 bug（此前一直手工敲等价 docker 命令，脚本本身从未被完整执行过）：
  ① 缺 `--cap-add=SYS_ADMIN`，zebra 静默起不来——watchfrr 照常拉起 staticd，但 zebra 进程不出现，vtysh 只报「zebra is not running」，真因 `privs_init: cap_set_proc failed` 藏在别处
  ② 客户端循环给两个容器都分配 `192.168.1.10`
  ③ `set -euo pipefail` 碰上 ping 在 100% 丢包时的非零退出码会当场退出——而「全断」恰恰是最该测出来的场景

- 前端首次有测试：`frontend/src/lib/format.js` + 12 个用例（node 内置 runner，零依赖）。此前 `package.json` 连 test 脚本都没有，CI 只 build 不 test
- CI 的 `frontend-build` job 补上 `npm test`
- 新门禁 `frontend-has-tests`：校验 test 脚本存在、测试文件存在、**且 App.jsx 真的 import 了被测模块**（否则测的是副本不是运行的那份）
- 新门禁 `deps-pinned-and-audited`：依赖不得出现 `>=` / `^` 浮动范围

### Security
- 依赖升级消除全部已知漏洞（`pip-audit` 与 `npm audit` 均 0）：fastapi 0.115.6→0.142.2（带 starlette 0.41.3→1.7.0，原有 19 条 CVE）、python-dotenv 1.0.1→1.2.2、pytest 8.3.4→9.0.3、langgraph 浮动→1.2.12、vite 8.0.13→8.3.2（连带修掉 nanoid/postcss 高危）

### Fixed
- `validate_project.py` 的路由提取在新版 FastAPI 上抛 `AttributeError`：0.142 起 `include_router` 产出 `_IncludedRouter` 包装对象，既无 `.path` 也无 `.routes`，真实路由在 `.original_router.routes`。改为逐层下钻、兼容三种容器形态
- `compactLabel` 的空值占位符从来没显示出来：原实现先取 `'--'` 再过 `[_-]+→' '` 规则，占位符被吃成单个空格。已短路返回
- `CliRunner(mix_stderr=...)` 在 click 8.2+ 已移除，改为版本兼容写法

- 真实闭环 `diagnose/closed_loop.py`：注入 → 诊断 → 处置 → 重测 → 验证。三条不可让步的规则：没重测不许报 success、重测没改善触发回滚、探针失败如实记异常
- 闭环的实验台适配 `diagnose/lab_adapter.py`（真调 tc / ip link / ping）
- `docs/closed-loop-run-report.md`：三场景真实跑测报告，并列出**不能**支撑的主张
- `test_closed_loop.py`：7 个反例优先的回归，重点是「处置无效时必须报失败」

### Fixed
- **自愈不再恒报成功**。`HealingReport.success` 此前默认值 `True` 且无任何代码赋值；
  `telemetry.heal()` 把 `fault` 改回 normal 再采一次样就算「处置成功」——与是否真做了事无关。
  现 `success` 只能由实测前后对比推出，`verified=False` 时恒为 False
- `test_core.py::test_fault_heal` 此前断言 `heal['success']` 为真——把假象写成了测试契约，
  反过来阻止修复。已改为断言「模拟路径必须承认未验证」

- 真实网络实验台 `scripts/lab.sh`：用 docker 起两个 FRR 路由器 + 客户端，布出真两跳 L3 路径（client1 → r1 → r2 → 远端段），并可注入 netem 拥塞与断链故障
- 真实遥测采集 `diagnose/lab_collector.py`：解析真实 ICMP 报文与网卡计数器，产出 measurement 而非常量
- 真实数据 fixture `tests/fixtures/lab/`：三态抓包原文 + 网卡计数器实测带宽
- `tests/test_real_lab.py`：11 个基于真实抓取的回归

### Fixed
- **诊断置信度不再是编造的常量**（违反 CONTRIBUTING 规则 2）。此前 link_down/congestion/anomaly_traffic 分别硬编码 .98/.92/.88，与证据无关——实验台实测同样 120ms 延迟（`tests/fixtures/lab/throughput-real.json`），带宽 18.66Mbps 与 4.01Mbps 的置信度完全相同。现由证据强度、样本量、是否有独立佐证推导
- **拥塞判定不再把延迟与带宽绑死**。旧规则要求 `latency_ms > 50 and throughput_mbps < 60`，60 是绝对 Mbps 阈值，在高速链路上同条件会漏判。实验台实测（数据见 `tests/fixtures/lab/throughput-real.json`，采集方式 `scripts/lab.sh measure`）：注入 120ms 延迟不限速时带宽 18.66Mbps，与健康态 21.08Mbps 接近——延迟升高与带宽受限是独立的两件事。现改为延迟劣化即可判定，带宽仅在给出基线时作佐证，且按相对跌幅判定
- **丢包以报文计数为准**，不再采信 ping 自报百分比（10 发 9 收自报 0%，回归见 `backend/tests/test_real_lab.py`）
- `TelemetrySnapshot.source` 增加 `real`/`lab` 取值——此前 Literal 只列模拟侧，真实采集的数据在 schema 层就存不进来

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
